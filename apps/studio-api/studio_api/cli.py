import argparse, getpass, sys
from uuid import UUID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .audit import audit
from .config import get_settings
from .db import SessionLocal
from .models import LocalIdentity, User, UserRole, UserStatus
from .source_deletion import run_one_source_cleanup
from .operational_alerts import record_postgres_backup_outcome, run_observability_canary
from .security import hash_password, normalize_email, utcnow
from .trace_context import new_trace_id

def bootstrap_admin():
    p=argparse.ArgumentParser(); p.add_argument("email"); args=p.parse_args()
    s=get_settings(); db=sessionmaker(bind=create_engine(s.sqlalchemy_url()), expire_on_commit=False)()
    if db.query(User).filter_by(role=UserRole.admin, status=UserStatus.active).first():
        print("Active bootstrap admin already exists", file=sys.stderr); return 2
    pw=getpass.getpass("Admin password: "); pw2=getpass.getpass("Confirm password: ")
    if pw != pw2 or len(pw) < 12: print("Password mismatch or too short", file=sys.stderr); return 2
    u=User(email=normalize_email(args.email), role=UserRole.admin, status=UserStatus.active); db.add(u); db.flush(); db.add(LocalIdentity(user_id=u.id, password_hash=hash_password(pw)))
    audit(db,"admin.bootstrap_created",actor_user_id=u.id,subject_user_id=u.id); db.commit(); print("Bootstrap admin created"); return 0
def cleanup_sources():
    s=get_settings(); db=SessionLocal()
    try:
        count=1 if run_one_source_cleanup(db, settings=s, owner_id="legacy-source-cleanup", now=utcnow()) else 0
    finally:
        db.close()
    print(f"Expired local-upload sources cleaned: {count}")
    return 0

def record_backup_outcome():
    parser=argparse.ArgumentParser()
    parser.add_argument("owner_user_id")
    parser.add_argument("outcome", choices=("success","failed"))
    args=parser.parse_args()
    try:
        owner_user_id=str(UUID(args.owner_user_id))
    except (ValueError, AttributeError):
        print("Invalid alert owner", file=sys.stderr); return 2
    db=SessionLocal()
    try:
        record_postgres_backup_outcome(db,owner_user_id=owner_user_id,succeeded=args.outcome=="success")
        db.commit()
    except Exception:
        db.rollback(); print("Backup outcome was not recorded", file=sys.stderr); return 2
    finally:
        db.close()
    print("Backup outcome recorded")
    return 0

def observability_alert_canary():
    parser=argparse.ArgumentParser()
    parser.add_argument("owner_user_id")
    args=parser.parse_args()
    try:
        owner_user_id=str(UUID(args.owner_user_id))
    except (ValueError, AttributeError):
        print("Invalid alert owner", file=sys.stderr); return 2
    settings=get_settings()
    trace_id=new_trace_id()
    db=SessionLocal()
    try:
        incident=run_observability_canary(
            db,
            owner_user_id=owner_user_id,
            settings=settings,
            trace_id=trace_id,
            now=utcnow(),
        )
        db.commit()
    except Exception:
        db.rollback(); print("Observability canary failed", file=sys.stderr); return 2
    finally:
        db.close()
    print(
        "OBSERVABILITY_ALERT_CANARY_OK "
        f"status={incident.status} generation={incident.lifecycle_generation} "
        f"occurrences={incident.occurrence_count} trace_id={trace_id}"
    )
    return 0


def recover_owner():
    from .owner_recovery import recover_local_owner
    parser = argparse.ArgumentParser(description="Local VPS operator recovery of the personal owner")
    parser.add_argument("owner_user_id", type=UUID)
    parser.add_argument("--reset-totp", action="store_true", help="Explicitly retire a lost second factor")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("Recovery requires an interactive terminal", file=sys.stderr)
        return 2
    email = input("Confirm the existing owner's email: ").strip()
    if args.reset_totp and input("Type RESET SECOND FACTOR to retire the lost factor: ") != "RESET SECOND FACTOR":
        print("Second-factor reset was not confirmed", file=sys.stderr)
        return 2
    password = getpass.getpass("New owner password: ")
    if password != getpass.getpass("Confirm new owner password: "):
        print("Passwords differ", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        recover_local_owner(db, owner_user_id=str(args.owner_user_id), confirmed_email=email,
                            new_password=password, reset_totp=args.reset_totp)
        db.commit()
    except Exception:
        db.rollback()
        print("Owner recovery failed; no changes committed", file=sys.stderr)
        return 2
    finally:
        db.close()
    print("Owner recovered; prior sessions and trusted browsers revoked")
    return 0

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "recover-local-owner":
        sys.argv.pop(1)
        return recover_owner()
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup-expired-sources":
        sys.argv.pop(1)
        return cleanup_sources()
    if len(sys.argv) > 1 and sys.argv[1] == "record-postgres-backup-outcome":
        sys.argv.pop(1)
        return record_backup_outcome()
    if len(sys.argv) > 1 and sys.argv[1] == "run-observability-alert-canary":
        sys.argv.pop(1)
        return observability_alert_canary()
    return bootstrap_admin()

if __name__ == "__main__": raise SystemExit(main())
