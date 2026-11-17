"""State promotion. No model. Bodies are still TODOs."""

import pytest


def test_promotion_never_auto_approves():
    """Session grants and permissive mode do not copy state.

    TODO: auto_approves_promotion() is False.
    TODO: a PromotionDecision(explicit=False) raises PromotionError for yes, no, and select.
    TODO: there is no helper that builds an explicit decision from model text.
    """
    pytest.skip("TODO")


def test_yes_no_and_select_use_the_host_preview():
    """The choice applies to items the host measured, not a model summary.

    TODO: preview_from_files of two /work files builds stable ids from the paths.
    TODO: user_promotion_decision("yes") selects both items.
    TODO: user_promotion_decision("no") selects nothing.
    TODO: user_promotion_decision("select", [first_id]) selects only that item.
    TODO: an id that is not in the preview raises PromotionError.
    TODO: a path outside /work is rejected while building the preview.
    """
    pytest.skip("TODO")


def test_promote_refuses_a_root_executor():
    """Container root must not become host root on the way out.

    TODO: assert_promotion_executor on a CommandExecutor while euid is 0 raises
          PromotionError.
    TODO: a RunAsCommandExecutor whose uid is 0 raises PromotionError.
    TODO: a RunAsCommandExecutor for a different linux username raises PromotionError.
    """
    pytest.skip("TODO")


def test_promote_writes_as_the_linux_user_under_that_home():
    """The copy uses the existing run-as write path.

    TODO: apply_promotion with a RunAsCommandExecutor for a non-root user.
    TODO: the WriteFileCommand path is under that user's home.
    TODO: a relative path of ../outside raises PromotionError and writes nothing.
    TODO: stat the written file and assert st_uid is the linux user's uid, not 0.
    """
    pytest.skip("TODO")


@pytest.mark.docker
def test_live_promoted_file_is_owned_by_the_user():
    """End to end, still with no model.

    TODO: as root inside the container, write /work/note.txt.
    TODO: host inspection reads those bytes and builds the preview.
    TODO: apply the user's yes choice through RunAsCommandExecutor.
    TODO: the host file is owned by linux_username and is not mode-set by a host root chown.
    """
    pytest.skip("TODO")
