"""Bounded Yandex Disk REST transport. No caller-selected hosts or raw errors."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
from urllib.parse import quote, urlsplit

import httpx

API_ORIGIN = "https://cloud-api.yandex.net/v1/disk"
RESOURCE_FIELDS = "resource_id,name,path,type,mime_type,size,md5,sha256,created,modified"
JSON_LIMIT = 1024 * 1024


class YandexDiskError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def normalize_disk_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("disk:/") or len(value) > 4096:
        raise YandexDiskError("invalid_path")
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise YandexDiskError("invalid_path")
    parts = value[6:].split("/")
    if any(p in {".", ".."} for p in parts) or any(not p for p in parts[:-1]):
        raise YandexDiskError("invalid_path")
    return value.rstrip("/") if value != "disk:/" else value


def signed_content_url(value: str) -> str:
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        valid = (u.scheme == "https" and u.port in (None,443) and u.username is None
                 and u.password is None and not u.fragment and len(value) <= 8192
                 and any(host.endswith(suffix) for suffix in (
                     ".disk.yandex.ru", ".disk.yandex.net", ".storage.yandex.net")))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise YandexDiskError("unsafe_content_url")
    return value


def disk_web_url(path: str) -> str:
    return "https://disk.yandex.ru/client/disk" + quote(normalize_disk_path(path)[5:], safe="/")


@dataclass(frozen=True)
class DiskResource:
    resource_id: str | None = field(repr=False)
    path: str = field(repr=False)
    name: str = field(repr=False)
    is_folder: bool
    mime_type: str | None
    size_bytes: int | None
    md5: str | None
    sha256: str | None
    created: str | None
    modified: str | None


def resource_from_payload(value) -> DiskResource:
    if not isinstance(value, dict) or value.get("type") not in {"file","dir"}:
        raise YandexDiskError("malformed_response")
    path = normalize_disk_path(value.get("path"))
    identity = value.get("resource_id")
    name = value.get("name")
    size = value.get("size")
    if ((identity is not None and (not isinstance(identity,str) or not 1 <= len(identity) <= 256))
            or not isinstance(name,str) or not 1 <= len(name) <= 512
            or (size is not None and (type(size) is not int or size < 0))):
        raise YandexDiskError("malformed_response")
    def optional_string(key):
        raw = value.get(key)
        if raw is not None and (not isinstance(raw,str) or len(raw)>512):
            raise YandexDiskError("malformed_response")
        return raw
    return DiskResource(identity,path,name,value["type"]=="dir",optional_string("mime_type"),size,
                        optional_string("md5"),optional_string("sha256"),optional_string("created"),optional_string("modified"))


def _check_status(code: int):
    if 200 <= code < 300:
        return
    reason = {401:"authentication_rejected",403:"permission_denied",404:"not_found",
              409:"conflict",413:"too_large",423:"resource_locked",429:"rate_limited",507:"quota_exceeded"}.get(code,"unavailable")
    if 300 <= code < 400:
        reason = "unsafe_redirect"
    raise YandexDiskError(reason)


class YandexDiskClient:
    def __init__(self, access_token: str, *, client: httpx.Client | None = None):
        if not isinstance(access_token,str) or not 1 <= len(access_token) <= 8192 or any(ord(c)<32 for c in access_token):
            raise YandexDiskError("authentication_rejected")
        self._token = access_token
        self._injected_client = client

    def __repr__(self):
        return "YandexDiskClient(<redacted>)"

    @contextmanager
    def _http(self):
        if self._injected_client is not None:
            yield self._injected_client
        else:
            with httpx.Client(timeout=httpx.Timeout(30,connect=10),follow_redirects=False,trust_env=False) as client:
                yield client

    def _json(self, path: str, *, params=None):
        try:
            with self._http() as client, client.stream("GET",API_ORIGIN+path,params=params,
                    headers={"Authorization":"OAuth "+self._token},follow_redirects=False) as response:
                _check_status(response.status_code)
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>JSON_LIMIT:raise YandexDiskError("malformed_response")
                payload=json.loads(content)
                if not isinstance(payload,dict):raise YandexDiskError("malformed_response")
                return payload
        except httpx.TimeoutException:
            raise YandexDiskError("timeout") from None
        except httpx.HTTPError:
            raise YandexDiskError("unavailable") from None
        except (ValueError,UnicodeError):
            raise YandexDiskError("malformed_response") from None

    def account_identity(self) -> str:
        user=self._json("",params={"fields":"user.uid"}).get("user")
        identity=user.get("uid") if isinstance(user,dict) else None
        if not isinstance(identity,str) or not 1<=len(identity)<=128:
            raise YandexDiskError("malformed_response")
        return identity

    def metadata(self,path: str) -> DiskResource:
        path=normalize_disk_path(path)
        result=resource_from_payload(self._json("/resources",params={"path":path,"fields":RESOURCE_FIELDS}))
        if result.path!=path:raise YandexDiskError("resource_changed")
        return result

    def children(self,path: str,*,offset: int=0,limit: int=50,sort: str="name"):
        path=normalize_disk_path(path)
        if type(offset) is not int or not 0<=offset<=100000 or type(limit) is not int or not 1<=limit<=100 or sort not in {"name","-name","modified","-modified"}:
            raise YandexDiskError("invalid_pagination")
        payload=self._json("/resources",params={"path":path,"offset":offset,"limit":limit,"sort":sort,
            "fields":RESOURCE_FIELDS+","+",".join("_embedded.items."+key for key in RESOURCE_FIELDS.split(","))+",_embedded.total,_embedded.offset"})
        parent=resource_from_payload(payload)
        if parent.path!=path or not parent.is_folder:raise YandexDiskError("not_folder")
        embedded=payload.get("_embedded")
        if not isinstance(embedded,dict):raise YandexDiskError("malformed_response")
        items,total,page_offset=embedded.get("items"),embedded.get("total"),embedded.get("offset")
        if (not isinstance(items,list) or len(items)>limit or type(total) is not int or total<0
                or page_offset!=offset or (not items and offset<total)):
            raise YandexDiskError("malformed_response")
        rows=tuple(resource_from_payload(v) for v in items)
        for row in rows:
            if row.path.rpartition("/")[0] != path.rstrip("/"):
                raise YandexDiskError("resource_changed")
        return parent,rows,(offset+len(rows) if offset+len(rows)<total else None)

    def download_to(self,resource: DiskResource,target,*,maximum_bytes: int,check=lambda: None) -> int:
        if resource.is_folder or resource.size_bytes is None or resource.size_bytes>maximum_bytes:
            raise YandexDiskError("too_large")
        check()
        link=self._json("/resources/download",params={"path":resource.path})
        url=signed_content_url(link.get("href"))
        if link.get("method")!="GET":raise YandexDiskError("malformed_response")
        size=0;md5=hashlib.md5(usedforsecurity=False);sha=hashlib.sha256()
        try:
            with self._http() as client, client.stream("GET",url,follow_redirects=False) as response:
                _check_status(response.status_code)
                for chunk in response.iter_bytes(1024*1024):
                    check()
                    size+=len(chunk)
                    if size>maximum_bytes or size>resource.size_bytes:raise YandexDiskError("size_mismatch")
                    target.write(chunk);md5.update(chunk);sha.update(chunk)
        except httpx.TimeoutException:raise YandexDiskError("timeout") from None
        except httpx.HTTPError:raise YandexDiskError("unavailable") from None
        if size!=resource.size_bytes or (resource.md5 and md5.hexdigest()!=resource.md5) or (resource.sha256 and sha.hexdigest()!=resource.sha256):
            raise YandexDiskError("integrity_mismatch")
        check()
        return size

    def upload_new(self,path: str,content: bytes) -> DiskResource:
        path=normalize_disk_path(path)
        link=self._json("/resources/upload",params={"path":path,"overwrite":"false"})
        url=signed_content_url(link.get("href"))
        if link.get("method")!="PUT":raise YandexDiskError("malformed_response")
        try:
            with self._http() as client:
                response=client.put(url,content=content,headers={"Content-Type":"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},follow_redirects=False)
                _check_status(response.status_code)
        except httpx.TimeoutException:raise YandexDiskError("timeout") from None
        except httpx.HTTPError:raise YandexDiskError("unavailable") from None
        result=self.metadata(path)
        if result.is_folder or result.size_bytes!=len(content) or result.md5!=hashlib.md5(content,usedforsecurity=False).hexdigest():
            raise YandexDiskError("integrity_mismatch")
        return result
