"""CRM tools for crm-followup. These are the LIVE tools — plain Python, so wiring a
real CRM here (Folk, HubSpot, a Postgres query) is just replacing the dicts with API
calls. Exams never hit this file if evals/<agent>/tools_mock.py exists; keeping exam
data deterministic while live tools talk to the real world (restaurant-brain pattern:
the model picks, the data stays deterministic)."""

_CRM = {
    "janssens bakery": {
        "contact": "Sofie Janssens", "status": "prospect",
        "last_interaction": "2026-07-02",
        "notes": "Wants a chatbot for the webshop, wants to go live before September.",
    },
    "devos garage": {
        "contact": "Jan De Vos", "status": "active client",
        "last_interaction": "2026-06-19",
        "notes": "Appointment-scheduling assistant delivered in June; happy, considering phase 2.",
    },
    "vitrine restaurant": {
        "contact": "Karel Mestdagh", "status": "churned",
        "last_interaction": "2026-03-11",
        "notes": "Paused the menu-QA pilot for budget reasons; revisit Q4.",
    },
}

_DEALS = {
    "janssens bakery": [
        {"deal": "Webshop chatbot", "amount_eur": 6500, "stage": "proposal sent"}],
    "devos garage": [
        {"deal": "Phase 2: quote assistant", "amount_eur": 9000, "stage": "discovery"}],
}


def _norm(company: str) -> str:
    return company.strip().lower()


def crm_lookup(company: str = "") -> dict:
    return _CRM.get(_norm(company), {"error": f"no CRM record for {company!r}"})


def deals_list(company: str = "") -> list | dict:
    return _DEALS.get(_norm(company), {"error": f"no open deals for {company!r}"})
