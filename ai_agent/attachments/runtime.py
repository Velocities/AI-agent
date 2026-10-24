"""Open the on-disk attachment store for an API process."""

from __future__ import annotations

import logging
import os
import stat

from ai_agent.attachments.cache import AttachmentCache
from ai_agent.attachments.ids import ID_RE
from ai_agent.attachments.os_store import OSAttachmentStore
from ai_agent.attachments.store import AttachmentStore
from ai_agent.config import Settings
from ai_agent.conversations.attachments import AttachmentCatalog
from ai_agent.conversations.user_settings import UserSettingsStore

logger = logging.getLogger(__name__)


def open_attachment_services(
    settings: Settings,
    engine,
) -> tuple[UserSettingsStore, AttachmentCatalog, AttachmentStore, AttachmentCache]:
    root = settings.resolved_attachment_root()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(stat.S_IRWXU)
    catalog = AttachmentCatalog(engine)
    user_settings = UserSettingsStore(engine)
    store = OSAttachmentStore(
        root,
        catalog,
        quota_bytes=settings.attachment_quota_bytes,
        quota_count=settings.attachment_quota_count,
    )
    cache = AttachmentCache(store, max_bytes=settings.attachment_cache_bytes)
    removed = reconcile_attachments(store, catalog)
    if removed:
        logger.info("Removed %s orphan attachment file(s)", removed)
    else:
        logger.info("Attachment reconcile found no orphan files")
    return user_settings, catalog, store, cache


def reconcile_attachments(store: OSAttachmentStore, catalog: AttachmentCatalog) -> int:
    """Delete files with no catalog row. Return how many files were removed.

    Catalog rows that lack a file are left in place. Symlinks and non-UUID
    names are skipped. Other users' catalogued files are not deleted.
    """
    known = catalog.all_ids()
    root = store.root
    if not root.is_dir() or root.is_symlink():
        return 0
    removed = 0
    with os.scandir(root) as users:
        for user in users:
            if user.is_symlink() or not user.is_dir(follow_symlinks=False):
                continue
            if not ID_RE.match(user.name):
                continue
            with os.scandir(user.path) as conversations:
                for conversation in conversations:
                    if conversation.is_symlink() or not conversation.is_dir(follow_symlinks=False):
                        continue
                    if not ID_RE.match(conversation.name):
                        continue
                    with os.scandir(conversation.path) as files:
                        for entry in files:
                            if entry.is_symlink():
                                continue
                            if not ID_RE.match(entry.name):
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            if entry.name in known:
                                continue
                            try:
                                os.unlink(entry.path)
                            except FileNotFoundError:
                                continue
                            removed += 1
    return removed
