"""api/meta.py — resource router stub (Phase 08 Plan 01).

Owns `router` for the meta resource. Plan 01 creates this empty stub so
api/router.py can import + include_router it ONCE. Later plans (02-05) add
`@router` handlers here only — they never edit api/router.py.
"""

from fastapi import APIRouter

router = APIRouter()
