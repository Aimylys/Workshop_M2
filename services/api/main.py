
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import Depends
from sqlalchemy import select
from prometheus_fastapi_instrumentator import Instrumentator

from auth import verify_password, create_access_token, decode_access_token
from models import User

from database import SessionLocal, check_database
from models import Account, Transaction
from schemas import (
    AccountResponse,
    TransactionRequest,
    TransactionResponse,
)

app = FastAPI(
    title="Resilience Alpha API",
    description="API bancaire fictive - Workshop 2026",
    version="0.2.0"
)
LOGIN_FAILED = Counter("login_failed_total", "Échecs d'authentification")
SQL_ERRORS = Counter("sql_errors_total", "Erreurs SQL / base de données")
TRANSACTIONS = Counter("transactions_total", "Virements traités", ["status"])
TRANSACTIONS.labels(status="success")   # crée la série à 0
TRANSACTIONS.labels(status="failed")
Instrumentator(should_instrument_requests_inprogress=True, inprogress_name="http_inprogress_requests",).instrument(app).expose(app)

@app.exception_handler(SQLAlchemyError)
def sql_error_handler(request: Request, exc: SQLAlchemyError):
    SQL_ERRORS.inc()
    return JSONResponse(status_code=500, content={"detail": "Erreur base de données"})

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/login"
)


def get_current_user(
    token: str = Depends(oauth2_scheme)
):
    user_id = decode_access_token(token)

    with SessionLocal() as db:
        user = db.get(User, user_id)

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Utilisateur introuvable",
                headers={"WWW-Authenticate": "Bearer"}
            )

        return user



@app.get("/")
def accueil():
    return {"message": "Bienvenue sur Resilience Alpha"}


@app.get("/health")
def health():
    try:
        check_database()
        return {"status": "UP", "database": "UP"}
    except SQLAlchemyError:
        SQL_ERRORS.inc()
        raise HTTPException(
            status_code=503,
            detail={"status": "DOWN", "database": "DOWN"}
        )


@app.get("/accounts", response_model=list[AccountResponse], dependencies=[Depends(get_current_user)])
def get_accounts():
    with SessionLocal() as db:
        return db.scalars(
            select(Account).order_by(Account.id)
        ).all()


@app.get("/accounts/{account_id}", response_model=AccountResponse, dependencies=[Depends(get_current_user)])
def get_account(account_id: int):
    with SessionLocal() as db:
        account = db.get(Account, account_id)

        if account is None:
            raise HTTPException(
                status_code=404,
                detail="Compte introuvable"
            )

        return account


def _execute_transaction(request: TransactionRequest):
    if request.source_account_id == request.destination_account_id:
        raise HTTPException(
            status_code=400,
            detail="Les comptes doivent être différents"
        )

    with SessionLocal() as db:
        with db.begin():
            # Verrouillage dans un ordre stable pour éviter
            # les virements concurrents incohérents.
            account_ids = sorted([
                request.source_account_id,
                request.destination_account_id
            ])

            accounts = db.scalars(
                select(Account)
                .where(Account.id.in_(account_ids))
                .order_by(Account.id)
                .with_for_update()
            ).all()

            by_id = {account.id: account for account in accounts}

            source = by_id.get(request.source_account_id)
            destination = by_id.get(request.destination_account_id)

            if source is None or destination is None:
                raise HTTPException(
                    status_code=404,
                    detail="Compte source ou destinataire introuvable"
                )

            if source.balance < request.amount:
                raise HTTPException(
                    status_code=400,
                    detail="Solde insuffisant"
                )

            source.balance -= request.amount
            destination.balance += request.amount

            transaction = Transaction(
                source_account_id=source.id,
                destination_account_id=destination.id,
                amount=request.amount
            )

            db.add(transaction)
            db.flush()

            result = TransactionResponse.model_validate(transaction)

        return result


@app.get("/transactions", response_model=list[TransactionResponse], dependencies=[Depends(get_current_user)])
def get_transactions():
    with SessionLocal() as db:
        return db.scalars(
            select(Transaction).order_by(Transaction.id)
        ).all()

@app.post("/transactions", response_model=TransactionResponse, dependencies=[Depends(get_current_user)])
def create_transaction(request: TransactionRequest):
    try:
        result = _execute_transaction(request)
    except Exception:
        TRANSACTIONS.labels(status="failed").inc()
        raise
    TRANSACTIONS.labels(status="success").inc()
    return result


@app.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                User.email == form_data.username
            )
        )

        if (
            user is None
            or user.password_hash is None
            or not verify_password(
                form_data.password,
                user.password_hash
            )
        ):
            LOGIN_FAILED.inc()
            raise HTTPException(
                status_code=401,
                detail="Identifiants incorrects",
                headers={"WWW-Authenticate": "Bearer"}
            )

        token = create_access_token(user.id)

        return {
            "access_token": token,
            "token_type": "bearer"
        }

