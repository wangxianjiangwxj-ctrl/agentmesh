"""Company Registry — In-Memory Repository.

Provides an in-memory data layer for Company and CompanyMember entities.
Designed for MVP / test usage; can be swapped for a SQL-backed
implementation later by implementing the same interface.
"""

from __future__ import annotations

from typing import Optional

from agentmesh.platform.company.models import (
    Company,
    CompanyMember,
    CompanyStatus,
)


class CompanyRepository:
    """In-memory repository for Company and CompanyMember entities.

    All data is stored in plain dicts keyed by company_id and
    (company_id, agent_id) respectively.  Thread-safety is not guaranteed
    — the caller should serialise access at the service layer.
    """

    def __init__(self) -> None:
        self._companies: dict[str, Company] = {}
        self._members: dict[tuple[str, str], CompanyMember] = {}

    # -- Company CRUD -------------------------------------------------------

    def create_company(self, company: Company) -> Company:
        """Persist a new company.

        Args:
            company: The Company object to store.

        Returns:
            The stored Company object (a copy).
        """
        self._companies[company.id] = company.model_copy(deep=True)
        return self.get_company(company.id)

    def get_company(self, company_id: str) -> Optional[Company]:
        """Fetch a company by ID.

        Args:
            company_id: The unique company identifier.

        Returns:
            A deep copy of the Company, or ``None`` if not found.
        """
        company = self._companies.get(company_id)
        if company is None:
            return None
        return company.model_copy(deep=True)

    def list_companies(self) -> list[Company]:
        """Return all registered companies.

        Returns:
            A list of deep-copied Company objects.
        """
        return [c.model_copy(deep=True) for c in self._companies.values()]

    def update_company_status(self, company_id: str, status: CompanyStatus) -> Optional[Company]:
        """Update the status of an existing company.

        Args:
            company_id: The unique company identifier.
            status: The new CompanyStatus value.

        Returns:
            The updated Company object, or ``None`` if the company
            does not exist.
        """
        company = self._companies.get(company_id)
        if company is None:
            return None
        company.status = status
        return company.model_copy(deep=True)

    # -- Membership CRUD ----------------------------------------------------

    def add_member(self, member: CompanyMember) -> CompanyMember:
        """Add an agent as a member of a company.

        If the membership already exists it will be **replaced**.

        Args:
            member: The CompanyMember object to persist.

        Returns:
            A deep copy of the stored CompanyMember.
        """
        key = (member.company_id, member.agent_id)
        self._members[key] = member.model_copy(deep=True)
        return self._members[key].model_copy(deep=True)

    def remove_member(self, company_id: str, agent_id: str) -> bool:
        """Remove an agent from a company.

        Args:
            company_id: The company identifier.
            agent_id: The agent identifier to remove.

        Returns:
            ``True`` if the member was found and removed, ``False``
            otherwise.
        """
        key = (company_id, agent_id)
        if key not in self._members:
            return False
        del self._members[key]
        return True

    def get_members(self, company_id: str) -> list[CompanyMember]:
        """Return all members of a given company.

        Args:
            company_id: The company identifier.

        Returns:
            A list of deep-copied CompanyMember objects.
        """
        return [m.model_copy(deep=True) for key, m in self._members.items() if key[0] == company_id]

    def get_companies_for_agent(self, agent_id: str) -> list[Company]:
        """Return all companies an agent is a member of.

        Args:
            agent_id: The agent identifier.

        Returns:
            A list of deep-copied Company objects.
        """
        company_ids = [key[0] for key in self._members if key[1] == agent_id]
        return [self._companies[cid].model_copy(deep=True) for cid in company_ids if cid in self._companies]

    def get_member(self, company_id: str, agent_id: str) -> Optional[CompanyMember]:
        """Return a specific membership record, or ``None``.

        Args:
            company_id: The company identifier.
            agent_id: The agent identifier.

        Returns:
            The CompanyMember for the given pair, or ``None``.
        """
        member = self._members.get((company_id, agent_id))
        if member is None:
            return None
        return member.model_copy(deep=True)
