from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.help_support.model import (
    HelpSupportQuestion,
    HelpSupportQuestionCreate,
    HelpSupportQuestionRead,
    HelpSupportQuestionUpdate,
)

router = APIRouter(prefix="/help-support", tags=["Help & Support"])

ADMIN_ROLES = {"root", "super_admin", "department_admin"}


def _assert_admin_role(role: str) -> None:
    if normalize_role(role) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")


@router.get("/questions", response_model=list[HelpSupportQuestionRead])
async def list_questions(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> list[HelpSupportQuestion]:
    _ = current_user
    rows = (
        await session.exec(
            select(HelpSupportQuestion).order_by(HelpSupportQuestion.updated_at.desc())
        )
    ).all()
    return rows


@router.post("/questions", response_model=HelpSupportQuestionRead, status_code=201)
async def create_question(
    payload: HelpSupportQuestionCreate,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> HelpSupportQuestion:
    _assert_admin_role(current_user.role)
    now = datetime.now(timezone.utc)
    row = HelpSupportQuestion(
        question=payload.question.strip(),
        answer=payload.answer.strip(),
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/questions/{question_id}", response_model=HelpSupportQuestionRead)
async def update_question(
    question_id: UUID,
    payload: HelpSupportQuestionUpdate,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> HelpSupportQuestion:
    _assert_admin_role(current_user.role)
    row = await session.get(HelpSupportQuestion, question_id)
    if not row:
        raise HTTPException(status_code=404, detail="Question not found.")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No changes provided.")

    if "question" in changes and changes["question"] is not None:
        row.question = str(changes["question"]).strip()
    if "answer" in changes and changes["answer"] is not None:
        row.answer = str(changes["answer"]).strip()
    row.updated_by = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/questions/{question_id}")
async def delete_question(
    question_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> dict:
    _assert_admin_role(current_user.role)
    row = await session.get(HelpSupportQuestion, question_id)
    if not row:
        raise HTTPException(status_code=404, detail="Question not found.")
    await session.delete(row)
    await session.commit()
    return {"detail": "Question deleted"}

