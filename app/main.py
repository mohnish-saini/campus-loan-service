"""Loan lifecycle with durable request IDs and retryable cross-service operations."""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, String, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

engine = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)
Sessions = sessionmaker(engine, expire_on_commit=False)
EQUIPMENT_URL = os.environ.get('EQUIPMENT_SERVICE_URL', 'http://equipment-service:8000')

class Base(DeclarativeBase):
    pass

class Loan(Base):
    __tablename__ = 'loans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(36))
    borrower_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    failure_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class LoanInput(BaseModel):
    loan_id: UUID
    equipment_id: UUID
    borrower_id: str = Field(min_length=1, max_length=80, pattern=r'.*\S.*')

class LoanOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    equipment_id: str
    borrower_id: str
    status: str
    failure_reason: str | None
    created_at: datetime
    returned_at: datetime | None

@asynccontextmanager
async def lifespan(app):
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(583)"))
        Base.metadata.create_all(connection)
    yield
    engine.dispose()

app = FastAPI(title='Campus Loan Service', version='1.0.0', lifespan=lifespan)

def db():
    with Sessions() as session:
        yield session

@app.get('/health/live')
def live():
    return {'status': 'ok', 'service': 'loan'}

@app.get('/health/ready')
def ready(session: Session = Depends(db)):
    try:
        session.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Database unavailable')
    return {'status': 'ready'}

def equipment_call(method, loan):
    try:
        response = httpx.request(method, f'{EQUIPMENT_URL}/equipment/{loan.equipment_id}/reservations/{loan.id}', timeout=3.0)
    except httpx.RequestError:
        raise HTTPException(503, 'Equipment service unreachable. Retry this operation with the same loan ID.')
    if response.status_code >= 500:
        raise HTTPException(503, 'Equipment service unavailable. Retry with the same loan ID.')
    return response

@app.post('/loans', response_model=LoanOutput, status_code=201)
def borrow(body: LoanInput, session: Session = Depends(db)):
    # Persist intent before the remote call. A crash/timeout can be recovered by replay.
    existing = session.get(Loan, str(body.loan_id))
    if existing is None:
        session.add(Loan(id=str(body.loan_id), equipment_id=str(body.equipment_id), borrower_id=body.borrower_id, status='PENDING'))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    loan = session.scalar(select(Loan).where(Loan.id == str(body.loan_id)).with_for_update().execution_options(populate_existing=True))
    if loan.equipment_id != str(body.equipment_id) or loan.borrower_id != body.borrower_id:
        raise HTTPException(409, 'Loan ID already belongs to another request')
    if loan.status == 'REJECTED':
        raise HTTPException(409, loan.failure_reason)
    if loan.status in ('ACTIVE', 'RETURNED'):
        return loan
    response = equipment_call('PUT', loan)
    if response.status_code in (404, 409):
        loan.status = 'REJECTED'
        loan.failure_reason = response.json().get('detail', 'Reservation rejected')
        session.commit()
        raise HTTPException(response.status_code, loan.failure_reason)
    if response.status_code != 200:
        raise HTTPException(502, 'Unexpected equipment response; retry with the same loan ID')
    loan.status = 'ACTIVE'
    session.commit()
    return loan

@app.get('/loans', response_model=list[LoanOutput])
def list_loans(borrower_id: str | None = None, offset: int = 0, limit: int = 100, session: Session = Depends(db)):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, 'offset must be nonnegative; limit must be 1 to 100')
    query = select(Loan).order_by(Loan.created_at)
    if borrower_id is not None:
        query = query.where(Loan.borrower_id == borrower_id)
    return session.scalars(query.offset(offset).limit(limit)).all()

@app.get('/loans/{loan_id}', response_model=LoanOutput)
def get_loan(loan_id: UUID, session: Session = Depends(db)):
    loan = session.get(Loan, str(loan_id))
    if loan is None:
        raise HTTPException(404, 'Loan not found')
    return loan

@app.post('/loans/{loan_id}/return', response_model=LoanOutput)
def return_loan(loan_id: UUID, session: Session = Depends(db)):
    loan = session.scalar(select(Loan).where(Loan.id == str(loan_id)).with_for_update())
    if loan is None:
        raise HTTPException(404, 'Loan not found')
    if loan.status == 'RETURNED':
        return loan
    if loan.status != 'ACTIVE':
        raise HTTPException(409, 'Only an active loan can be returned; retry a pending borrowing request first')
    response = equipment_call('DELETE', loan)
    if response.status_code != 200:
        raise HTTPException(502, 'Reservation release failed; retry this return operation')
    loan.status = 'RETURNED'
    loan.returned_at = datetime.now(timezone.utc)
    session.commit()
    return loan
