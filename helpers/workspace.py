"""
subagent_workspace -- give delegate_parallel's local subs a real working directory.

Modes (config key ``subagent_workspace``, default ``none``):

  none      Today's behavior. Subs run in the global workdir (no project) -- they don't see the
            orchestrator's repo and all share one folder.
  inherit   Each sub gets the PARENT's project activated (shared folder). Good for parallel
            READ / analysis. NOT safe for parallel editing -- subs share one working tree.
  isolated  Each sub gets its OWN git worktree (+ its own branch) of the parent's repo, registered
            as a project, so subs can EDIT in parallel without colliding. Worktrees share one .git
            object store (near-free, no extra clone, no token). If the parent isn't a git repo,
            falls back to ``inherit``.

Worktree ownership / composition:
  ``isolated`` delegates to the **a0_worktree** plugin when it is installed -- it is the
  authoritative owner of git-worktree lifecycle (single owner when both are present). Detection is
  an EXACT probe of a0_worktree's versioned contract module; anything else is treated as foreign and
  left alone. When a0_worktree is absent, swarm uses its own inline worktree.

Good-neighbor design (coexist with foreign/uncooperative worktree managers AND manual user
worktrees -- you cannot make a third party follow your protocol, so never depend on or damage what
you don't own):
  * act ONLY on worktrees/projects carrying our ownership marker (never enumerate-and-remove all)
  * unique, namespaced, high-entropy keys; FAIL SAFE on path collision (never --force over a dir)
  * delegate ONLY to the exact a0_worktree contract module (never auto-call "anything worktree-ish")
  * serialize our own git-worktree mutations with a process lock; teardown is idempotent + tolerant
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid

from helpers import projects, files

logger = logging.getLogger(__name__)

OWNER = "a0_swarm"
MARKER_NAME = ".a0_swarm_owner.json"  # written into the worktree project's .a0proj meta dir

# ---- a0_worktree delegation contract (exact, versioned module probe) ----------------------------
# The authoritative worktree plugin, when installed, must expose this module providing:
#   CONTRACT_VERSION: int (>= REQUIRED_CONTRACT_VERSION)
#   create_worktree(repo_path: str, branch: str, key: str) -> str   # returns the A0 project name
#   remove_worktree(key: str) -> None                                # idempotent; only removes its own
A0_WORKTREE_CONTRACT_MODULE = "usr.plugins.a0_worktree.helpers.contract"
REQUIRED_CONTRACT_VERSION = 1


# ------------------------------------------------------------------------------------------------
# small utilities
# ------------------------------------------------------------------------------------------------
def _lock() -> threading.Lock:
    # Tools are re-imported per call (module globals reset), so shared state lives on sys -- and is
    # namespaced per plugin so two plugins can never clobber each other's state.
    lk = getattr(sys, "_a0_swarm_workspace_lock", None)
    if lk is None:
        lk = threading.Lock()
        sys._a0_swarm_workspace_lock = lk  # type: ignore[attr-defined]
    return lk


def _git(args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()[:300]}")
    return r


def _is_git_repo(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    return _git(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False).returncode == 0


def _new_key(run_id, index) -> str:
    short = "".join(c for c in str(run_id) if c.isalnum())[:8] or "run"
    return f"sw_{short}_{index}_{uuid.uuid4().hex[:6]}"


def a0_worktree_contract():
    """Return the a0_worktree contract module IF installed + compatible, else None (exact probe)."""
    try:
        import importlib
        import importlib.util

        if importlib.util.find_spec(A0_WORKTREE_CONTRACT_MODULE) is None:
            return None
        mod = importlib.import_module(A0_WORKTREE_CONTRACT_MODULE)
        if int(getattr(mod, "CONTRACT_VERSION", 0)) < REQUIRED_CONTRACT_VERSION:
            return None
        if not (callable(getattr(mod, "create_worktree", None))
                and callable(getattr(mod, "remove_worktree", None))):
            return None
        return mod
    except Exception as e:  # never let a foreign module break us
        logger.warning("a0_worktree probe failed (%s); using inline worktree.", e)
        return None


# ------------------------------------------------------------------------------------------------
# ownership marker (good-neighbor: only ever touch what carries OUR marker)
# ------------------------------------------------------------------------------------------------
def _marker_path(key: str) -> str:
    return os.path.join(projects.get_project_meta(key), MARKER_NAME)


def _write_marker(key, repo_path, branch, ctx_id):
    meta = projects.get_project_meta(key)
    files.create_dir(meta)
    with open(_marker_path(key), "w") as f:
        json.dump(
            {"owner": OWNER, "key": key, "repo_path": repo_path, "branch": branch,
             "ctx_id": ctx_id, "created": time.time()},
            f,
        )


def _read_marker(key):
    try:
        with open(_marker_path(key)) as f:
            d = json.load(f)
        return d if d.get("owner") == OWNER else None
    except Exception:
        return None


def _has_marker(key) -> bool:
    return _read_marker(key) is not None


# ------------------------------------------------------------------------------------------------
# inline worktree (used only when a0_worktree is absent)
# ------------------------------------------------------------------------------------------------
def _inline_create_worktree(repo_path, branch, key, ctx_id) -> str:
    """git worktree add at usr/projects/<key> + register as a project. Raises FileExistsError on
    a path collision (caller retries with a fresh key -- we NEVER overwrite an existing dir)."""
    target = projects.get_project_folder(key)
    if os.path.exists(target):
        raise FileExistsError(target)
    with _lock():
        _git(["-C", repo_path, "worktree", "add", "-b", branch, target])
    # keep our project meta out of the sub's git status
    try:
        ex = _git(["-C", target, "rev-parse", "--git-path", "info/exclude"]).stdout.strip()
        ex_abs = ex if os.path.isabs(ex) else os.path.join(target, ex)
        with open(ex_abs, "a") as f:
            f.write("\n.a0proj/\n")
    except Exception:
        pass
    projects.create_project_meta_folders(key)
    projects.save_project_header(key, projects._normalizeBasicData({"title": f"swarm worktree {key}"}))
    _write_marker(key, repo_path, branch, ctx_id)
    return key


def _inline_remove_worktree(key, repo_path=None):
    marker = _read_marker(key)
    if marker is None:
        logger.info("inline_remove: no a0_swarm marker for %s; leaving it alone.", key)
        return
    target = projects.get_project_folder(key)
    rp = repo_path or marker.get("repo_path")
    try:
        if rp and os.path.isdir(rp):
            with _lock():
                _git(["-C", rp, "worktree", "remove", "--force", target], check=False)
                _git(["-C", rp, "worktree", "prune"], check=False)
    except Exception:
        pass
    try:
        projects.delete_project(key)
    except Exception:
        pass
    shutil.rmtree(target, ignore_errors=True)  # only ours -- marker was checked above


# ------------------------------------------------------------------------------------------------
# Workspace handle (teardown is best-effort + idempotent)
# ------------------------------------------------------------------------------------------------
class Workspace:
    def __init__(self, mode, sub_ctx_id, *, project_name=None, owns_project=False,
                 key=None, repo_path=None, delegated=False, branch=None):
        self.mode = mode                  # effective mode actually applied
        self.sub_ctx_id = sub_ctx_id
        self.project_name = project_name  # project activated on the sub (None for 'none')
        self.owns_project = owns_project  # True ONLY for an isolated worktree/clone WE created
        self.key = key
        self.repo_path = repo_path
        self.delegated = delegated        # isolated handled by the a0_worktree contract
        self.branch = branch              # the sub's branch (isolated) -- surfaced for merging

    def teardown(self):
        try:
            projects.deactivate_project(self.sub_ctx_id, mark_dirty=False)
        except Exception:
            pass
        if not self.owns_project:
            return  # 'none'/'inherit': never delete the parent's (or no) project
        try:
            if self.delegated:
                mod = a0_worktree_contract()
                if mod is not None:
                    mod.remove_worktree(self.key)
                    return
                # contract vanished mid-run -> best-effort inline removal of OUR OWN dir
            _inline_remove_worktree(self.key, self.repo_path)
        except Exception as e:
            logger.warning("workspace teardown failed for key=%s: %s", self.key, e)


# ------------------------------------------------------------------------------------------------
# setup -- called in execute() BEFORE the sub's monologue (so the project is active for its cwd)
# ------------------------------------------------------------------------------------------------
def setup(mode, parent_project, sub_ctx, run_id, index) -> Workspace:
    mode = (mode or "none").strip().lower()
    if mode not in ("none", "inherit", "isolated"):
        logger.warning("unknown subagent_workspace=%r; treating as none", mode)
        mode = "none"

    if mode == "none":
        return Workspace("none", sub_ctx.id)

    if not parent_project:
        logger.info("subagent_workspace=%s but the parent has no active project; using global workdir.", mode)
        return Workspace("none", sub_ctx.id)

    if mode == "inherit":
        return _activate_inherit(parent_project, sub_ctx)

    # mode == "isolated"
    repo_path = projects.get_project_folder(parent_project)
    if not _is_git_repo(repo_path):
        logger.info("isolated: parent project %s is not a git repo; falling back to inherit.", parent_project)
        return _activate_inherit(parent_project, sub_ctx)

    for _ in range(3):  # retry on (rare) key/path collision -- never overwrite
        key = _new_key(run_id, index)
        branch = f"swarm/{key}"
        mod = a0_worktree_contract()
        if mod is not None:
            try:
                with _lock():
                    name = mod.create_worktree(repo_path, branch, key)
                projects.activate_project(sub_ctx.id, name, mark_dirty=False)
                return Workspace("isolated", sub_ctx.id, project_name=name, owns_project=True,
                                 key=name, repo_path=repo_path, delegated=True, branch=branch)
            except Exception as e:
                logger.warning("a0_worktree.create_worktree failed (%s); using inline worktree.", e)
                # fall through to inline for this attempt
        try:
            name = _inline_create_worktree(repo_path, branch, key, sub_ctx.id)
            projects.activate_project(sub_ctx.id, name, mark_dirty=False)
            return Workspace("isolated", sub_ctx.id, project_name=name, owns_project=True,
                             key=name, repo_path=repo_path, delegated=False, branch=branch)
        except FileExistsError:
            continue  # collision -> fresh key
        except Exception as e:
            logger.warning("isolated inline worktree failed (%s); falling back to inherit.", e)
            break

    return _activate_inherit(parent_project, sub_ctx)


def _activate_inherit(parent_project, sub_ctx) -> Workspace:
    try:
        projects.activate_project(sub_ctx.id, parent_project, mark_dirty=False)
        return Workspace("inherit", sub_ctx.id, project_name=parent_project, owns_project=False)
    except Exception as e:
        logger.warning("inherit activate failed (%s); using global workdir.", e)
        return Workspace("none", sub_ctx.id)


# ------------------------------------------------------------------------------------------------
# crash-safe sweep -- reclaim isolated worktrees WE own whose sub-context is gone.
# Scoped strictly to our ownership marker (foreign worktrees are invisible to this).
# ------------------------------------------------------------------------------------------------
def sweep_orphans(active_context_ids):
    try:
        parent = projects.get_projects_parent_folder()
        if not os.path.isdir(parent):
            return
        active = set(active_context_ids or [])
        for name in os.listdir(parent):
            marker = _read_marker(name)
            if marker is None:
                continue  # not ours -> leave alone
            ctx = marker.get("ctx_id")
            if ctx and ctx in active:
                continue  # still in use
            _inline_remove_worktree(name, marker.get("repo_path"))
    except Exception as e:
        logger.warning("sweep_orphans failed: %s", e)
