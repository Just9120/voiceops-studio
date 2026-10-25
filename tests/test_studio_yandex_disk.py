import hashlib
import io
import os
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL","sqlite+pysqlite:///:memory:")
from studio_api.yandex_disk import YandexDiskClient,YandexDiskError,normalize_disk_path,resource_from_payload,signed_content_url


def resource(path="disk:/test.flac",data=b"test",kind="file"):
    return dict(resource_id="opaque-resource-id",path=path,name=path.rsplit("/",1)[-1] or "Disk",
                type=kind,mime_type="audio/flac",size=len(data),md5=hashlib.md5(data,usedforsecurity=False).hexdigest(),
                sha256=hashlib.sha256(data).hexdigest())


def client(handler):
    return YandexDiskClient("synthetic-token",client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("path", ["http://attacker.test/","disk:/../other","disk:/a/./b","disk://a","disk:/a\nb","disk:/a\\b",None])
def test_rejects_noncanonical_paths(path):
    with pytest.raises(YandexDiskError):normalize_disk_path(path)


@pytest.mark.parametrize("url", ["http://x.disk.yandex.ru/a","https://127.0.0.1/a","https://evil.test/a",
    "https://disk.yandex.ru.evil.test/a","https://x.disk.yandex.ru:444/a","https://u:p@x.disk.yandex.ru/a",
    "https://x.disk.yandex.ru/a#fragment",None])
def test_signed_links_never_accept_arbitrary_origins_or_userinfo(url):
    with pytest.raises(YandexDiskError):signed_content_url(url)


def test_page_has_authorized_parent_and_explicit_pagination():
    def handler(req):
        assert req.headers["authorization"]=="OAuth synthetic-token"
        assert req.url.params["sort"]=="-modified"
        parent=resource("disk:/Folder",kind="dir")
        parent["_embedded"]={"items":[resource("disk:/Folder/a.flac")],"total":2,"offset":0}
        return httpx.Response(200,json=parent)
    parent,rows,next_offset=client(handler).children("disk:/Folder",limit=1,sort="-modified")
    assert parent.is_folder and len(rows)==1 and next_offset==1
    assert rows[0].path=="disk:/Folder/a.flac"
    assert "Folder" not in repr(rows[0])


def test_empty_folder_is_a_valid_terminal_page():
    p=resource("disk:/Empty",kind="dir");p["_embedded"]={"items":[],"total":0,"offset":0}
    assert client(lambda req:httpx.Response(200,json=p)).children("disk:/Empty")[1:]==((),None)


@pytest.mark.parametrize("status,reason", [(401,"authentication_rejected"),(403,"permission_denied"),
    (404,"not_found"),(409,"conflict"),(429,"rate_limited"),(507,"quota_exceeded"),(302,"unsafe_redirect")])
def test_provider_errors_are_normalized_without_payload_or_url(status,reason):
    c=client(lambda req:httpx.Response(status,text="private provider detail",headers={"Location":"http://attacker.test"}))
    with pytest.raises(YandexDiskError) as e:c.metadata("disk:/private.flac")
    assert str(e.value)==reason


def test_download_verifies_size_and_digest_without_forwarding_oauth_token():
    data=b"synthetic source";row=resource_from_payload(resource(data=data));seen=[]
    def handler(req):
        seen.append(str(req.url))
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/content?opaque=signed","method":"GET"})
        assert "authorization" not in req.headers
        return httpx.Response(200,content=data)
    target=io.BytesIO()
    assert client(handler).download_to(row,target,maximum_bytes=100)==len(data)
    assert target.getvalue()==data and len(seen)==2


def test_mismatching_download_is_not_accepted_as_source():
    def handler(req):
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/a","method":"GET"})
        return httpx.Response(200,content=b"FAIL")
    with pytest.raises(YandexDiskError,match="integrity_mismatch"):
        client(handler).download_to(resource_from_payload(resource()),io.BytesIO(),maximum_bytes=4)


def test_download_follows_validated_storage_redirect_without_credentials():
    data=b"synthetic source";seen=[]
    def handler(req):
        seen.append(req.url.host)
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/a?signature=opaque","method":"GET"})
        assert req.method=="GET" and "authorization" not in req.headers
        if req.url.host=="downloader.disk.yandex.ru":
            return httpx.Response(302,headers={"Location":"https://mds.storage.yandex.net/source?signature=another"})
        return httpx.Response(200,content=data)
    target=io.BytesIO()
    assert client(handler).download_to(resource_from_payload(resource(data=data)),target,maximum_bytes=100)==len(data)
    assert target.getvalue()==data
    assert seen==["cloud-api.yandex.net","downloader.disk.yandex.ru","mds.storage.yandex.net"]


@pytest.mark.parametrize("status", [301,302,303,307,308])
def test_download_accepts_three_validated_redirects_including_relative_locations(status):
    seen=[]
    def handler(req):
        seen.append(str(req.url))
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/start","method":"GET"})
        assert "authorization" not in req.headers
        if req.url.path!="/3":
            return httpx.Response(status,headers={"Location":"/"+str(len(seen)-1)})
        return httpx.Response(200,content=b"test")
    target=io.BytesIO()
    assert client(handler).download_to(resource_from_payload(resource()),target,maximum_bytes=4)==4
    assert len(seen)==5 and target.getvalue()==b"test"


@pytest.mark.parametrize("location", ["http://mds.storage.yandex.net/a","https://evil.test/a",
    "https://127.0.0.1/a","https://mds.storage.yandex.net.evil.test/a",
    "https://u:p@mds.storage.yandex.net/a","https://mds.storage.yandex.net:444/a",
    "https://mds.storage.yandex.net/a#fragment"])
def test_download_never_contacts_forbidden_redirect(location):
    seen=[]
    def handler(req):
        seen.append(req.url.host)
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/a","method":"GET"})
        assert "authorization" not in req.headers
        return httpx.Response(302,headers={"Location":location})
    target=io.BytesIO()
    with pytest.raises(YandexDiskError,match="unsafe_content_url"):
        client(handler).download_to(resource_from_payload(resource()),target,maximum_bytes=4)
    assert seen==["cloud-api.yandex.net","downloader.disk.yandex.ru"] and target.getvalue()==b""


@pytest.mark.parametrize("mode", ["missing","loop","limit"])
def test_download_redirect_chain_is_bounded(mode):
    seen=[]
    def handler(req):
        seen.append(req.url.path)
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/a","method":"GET"})
        assert "authorization" not in req.headers
        headers={} if mode=="missing" else {"Location":"/a" if mode=="loop" else "/hop"+str(len(seen))}
        return httpx.Response(307,headers=headers)
    with pytest.raises(YandexDiskError,match="unsafe_redirect"):
        client(handler).download_to(resource_from_payload(resource()),io.BytesIO(),maximum_bytes=4)
    assert len(seen)==(5 if mode=="limit" else 2)


@pytest.mark.parametrize("failure", ["size","hash","cancel"])
def test_redirected_download_preserves_integrity_and_cancellation_guards(failure):
    seen=[]
    def handler(req):
        seen.append(req.url.host)
        if req.url.host=="cloud-api.yandex.net":
            return httpx.Response(200,json={"href":"https://downloader.disk.yandex.ru/a","method":"GET"})
        assert "authorization" not in req.headers
        if req.url.host=="downloader.disk.yandex.ru":
            return httpx.Response(302,headers={"Location":"https://mds.storage.yandex.net/a"})
        return httpx.Response(200,content=b"too long" if failure=="size" else b"FAIL")
    def check():
        if failure=="cancel" and len(seen)==2:raise RuntimeError("owner cancelled")
    if failure=="cancel":
        with pytest.raises(RuntimeError,match="owner cancelled"):
            client(handler).download_to(resource_from_payload(resource()),io.BytesIO(),maximum_bytes=4,check=check)
        assert seen==["cloud-api.yandex.net","downloader.disk.yandex.ru"]
    else:
        with pytest.raises(YandexDiskError,match="size_mismatch" if failure=="size" else "integrity_mismatch"):
            client(handler).download_to(resource_from_payload(resource()),io.BytesIO(),maximum_bytes=4,check=check)


def test_upload_is_create_only_and_readback_verifies_exact_content():
    calls=[];data=b"synthetic docx placeholder"
    def handler(req):
        calls.append((req.method,req.url.path))
        if req.url.path.endswith("/upload"):
            assert req.url.params["overwrite"]=="false"
            return httpx.Response(200,json={"href":"https://uploader.disk.yandex.ru/a","method":"PUT"})
        if req.method=="PUT":
            assert req.content==data and "authorization" not in req.headers
            return httpx.Response(201)
        return httpx.Response(200,json=resource("disk:/result.docx",data=data))
    result=client(handler).upload_new("disk:/result.docx",data)
    assert result.path=="disk:/result.docx" and len(calls)==3


def test_upload_conflict_never_issues_a_write():
    seen=[]
    def handler(req):
        seen.append(req.method)
        return httpx.Response(409,json={"error":"file exists"})
    with pytest.raises(YandexDiskError,match="conflict"):client(handler).upload_new("disk:/result.docx",b"doc")
    assert seen==["GET"]


def test_large_or_malformed_metadata_fails_closed():
    with pytest.raises(YandexDiskError,match="malformed_response"):
        client(lambda req:httpx.Response(200,content=b"x"*(1024*1024+1))).metadata("disk:/f")
    with pytest.raises(YandexDiskError):resource_from_payload(resource()|{"size":True})
