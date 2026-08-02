"""Feature flags for temporary MVP behaviour.

Everything here is meant to be switched off once the product matures, so each
flag is defined in one place and documented with what turning it off restores.
"""

import os


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


#: MVP: mark a student as verified the moment their profile is created.
#:
#: Students would otherwise have to upload KYC documents and wait for an admin to
#: approve them before booking a ride. For the MVP a completed profile is enough.
#:
#: Turning this off restores the full checklist: profile -> documents -> approval.
#: Nothing else needs changing, because the verification checklist itself is
#: untouched -- an approved student simply satisfies every student step.
#:
#: Deliberately scoped to students. Drivers still need a valid licence, an
#: approved vehicle and admin approval, which are safety requirements rather
#: than paperwork.
MVP_AUTO_VERIFY_STUDENTS = _env_flag("MVP_AUTO_VERIFY_STUDENTS", True)
