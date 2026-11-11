"""Google implementation; DTOs and grant lifecycle remain capability scoped."""
class GoogleFilesProvider:
    def access_token(self, db, *, user_id: str, settings) -> str:
        from .google_connection_access import refresh_user_google_drive_access_token
        return refresh_user_google_drive_access_token(db, user_id=user_id, settings=settings)

    def metadata(self, token: str, resource_id: str, *, revision_id: str | None = None):
        from .google_drive import fetch_drive_file_metadata
        kwargs = {"revision_id": revision_id} if revision_id is not None else {}
        return fetch_drive_file_metadata(token, resource_id, **kwargs)

    def content(self, token: str, resource_id: str, *, revision_id: str | None = None):
        from .google_drive import fetch_drive_file_content
        return fetch_drive_file_content(token, resource_id, revision_id=revision_id)

    def folder_children(self, token: str, folder_id: str, **kwargs):
        from .google_drive import list_drive_folder_children
        return list_drive_folder_children(token, folder_id, **kwargs)
