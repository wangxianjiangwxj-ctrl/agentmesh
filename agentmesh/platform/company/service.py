"""Company Registry — Business Logic Service.

Provides the public API for agent company management:
- Create / dissolve companies (founder-gated)
- Join / leave companies (founder cannot leave — must dissolve or transfer)
- List / detail queries
"""
from __future__ import annotations

import uuid
from typing import Optional

from agentmesh.platform.company.models import (
    Company,
    CompanyDetail,
    CompanyMember,
    CompanyRole,
    CompanyStatus,
)
from agentmesh.platform.company.repository import CompanyRepository


class CompanyService:
    """High-level service for agent company management.

    Wraps the ``CompanyRepository`` with business rules such as:
    - Only the founder may dissolve a company.
    - The founder cannot leave a company (must dissolve or transfer).
    - Joining a dissolved company is refused.

    Args:
        repository: The data repository to use.  Defaults to a fresh
            in-memory ``CompanyRepository``.
    """

    def __init__(self, repository: Optional[CompanyRepository] = None) -> None:
        self._repo = repository or CompanyRepository()

    # -- Company lifecycle --------------------------------------------------

    def create_company(self, name: str, description: str, founder_id: str) -> dict:
        """Create a new company and auto-enrol the founder.

        Args:
            name: Human-readable company name (must be non-empty).
            description: Optional description.
            founder_id: Agent ID of the founding agent.

        Returns:
            A dict representation of the created Company with its
            founder membership.

        Raises:
            ValueError: If ``name`` is empty.
        """
        if not name or not name.strip():
            raise ValueError("Company name must not be empty")

        company_id = uuid.uuid4().hex
        company = Company(
            id=company_id,
            name=name.strip(),
            description=description,
            founder_id=founder_id,
        )
        self._repo.create_company(company)

        # Auto-enrol the founder
        founder_member = CompanyMember(
            company_id=company_id,
            agent_id=founder_id,
            role=CompanyRole.FOUNDER,
        )
        self._repo.add_member(founder_member)

        result = company.model_dump()
        result["members"] = [founder_member.model_dump()]
        return result

    def dissolve_company(self, company_id: str, agent_id: str) -> dict:
        """Dissolve a company (founder only).

        Args:
            company_id: The company to dissolve.
            agent_id: The agent requesting the dissolution.

        Returns:
            The updated Company dict with status ``dissolved``.

        Raises:
            ValueError: If the company does not exist, is already
                dissolved, or the requester is not the founder.
        """
        company = self._repo.get_company(company_id)
        if company is None:
            raise ValueError(f"Company '{company_id}' not found")

        if company.founder_id != agent_id:
            raise ValueError(
                f"Agent '{agent_id}' is not the founder of company "
                f"'{company_id}' and cannot dissolve it"
            )

        if company.status == CompanyStatus.DISSOLVED:
            raise ValueError(f"Company '{company_id}' is already dissolved")

        updated = self._repo.update_company_status(company_id, CompanyStatus.DISSOLVED)
        return updated.model_dump()

    # -- Membership management ----------------------------------------------

    def join_company(self, company_id: str, agent_id: str) -> dict:
        """Have an agent join an active company.

        Args:
            company_id: The company to join.
            agent_id: The agent who wants to join.

        Returns:
            The new CompanyMember dict.

        Raises:
            ValueError: If the company is not found, is dissolved,
                or the agent is already a member.
        """
        company = self._repo.get_company(company_id)
        if company is None:
            raise ValueError(f"Company '{company_id}' not found")

        if company.status == CompanyStatus.DISSOLVED:
            raise ValueError(
                f"Cannot join company '{company_id}' because it is dissolved"
            )

        existing = self._repo.get_member(company_id, agent_id)
        if existing is not None:
            raise ValueError(
                f"Agent '{agent_id}' is already a member of company "
                f"'{company_id}'"
            )

        member = CompanyMember(
            company_id=company_id,
            agent_id=agent_id,
            role=CompanyRole.MEMBER,
        )
        self._repo.add_member(member)
        return member.model_dump()

    def leave_company(self, company_id: str, agent_id: str) -> dict:
        """Remove an agent from a company.

        The founder **cannot** leave — they must dissolve the company
        or transfer ownership first.

        Args:
            company_id: The company to leave.
            agent_id: The agent who wants to leave.

        Returns:
            A dict confirming the departure with the affected company_id
            and agent_id.

        Raises:
            ValueError: If the company is not found, the agent is not
                a member, or the agent is the founder.
        """
        company = self._repo.get_company(company_id)
        if company is None:
            raise ValueError(f"Company '{company_id}' not found")

        member = self._repo.get_member(company_id, agent_id)
        if member is None:
            raise ValueError(
                f"Agent '{agent_id}' is not a member of company "
                f"'{company_id}'"
            )

        if company.founder_id == agent_id:
            raise ValueError(
                f"Founder of company '{company_id}' cannot leave. "
                "Dissolve the company or transfer ownership first."
            )

        self._repo.remove_member(company_id, agent_id)
        return {"company_id": company_id, "agent_id": agent_id, "action": "left"}

    # -- Queries ------------------------------------------------------------

    def list_companies(self) -> list[dict]:
        """Return all registered companies.

        Returns:
            A list of Company dicts.
        """
        return [c.model_dump() for c in self._repo.list_companies()]

    def get_company_detail(self, company_id: str) -> dict:
        """Return full company detail including its member list.

        Args:
            company_id: The company to inspect.

        Returns:
            A dict with keys ``company`` and ``members``.

        Raises:
            ValueError: If the company does not exist.
        """
        company = self._repo.get_company(company_id)
        if company is None:
            raise ValueError(f"Company '{company_id}' not found")

        members = self._repo.get_members(company_id)
        return CompanyDetail(
            company=company,
            members=members,
        ).model_dump()

    def get_agent_companies(self, agent_id: str) -> list[dict]:
        """Return all companies an agent belongs to.

        Args:
            agent_id: The agent to look up.

        Returns:
            A list of Company dicts for companies the agent is a
            member of (including the company they founded).
        """
        return [c.model_dump() for c in self._repo.get_companies_for_agent(agent_id)]
