# Security Policy

resecta-sample-doc generates synthetic test documents — a multi-exhibit
loan/mortgage packet and a sample bank statement — used as labeled corpora and
in-app samples for the Resecta iOS redaction app. It processes no real user
data. The security-relevant property of this repository is that its outputs stay
synthetic and deterministic.

## Reporting a vulnerability

- **Email:** `security@resecta.app`.
- **GitHub Security Advisories:** open a private advisory on this repository's
  *Security* tab.

Please do not open public issues for security reports until coordinated
disclosure has been agreed upon.

### What to expect

- **Acknowledgement:** within 7 days of receipt.
- **Triage update:** within 30 days of acknowledgement.

## Scope

**In scope:**

- The Python generator code (`packet/`, `generate_statement.py`,
  `statement_data.py`, `verify.py`, and related modules).
- Any defect that could cause real personal data to enter a generated document,
  or that breaks the byte-reproducibility of the outputs.

**Out of scope:**

- The Resecta iOS app and the data pipeline — report those through their own
  repositories.
- The bundled Inter font (SIL OFL 1.1) — report upstream at
  [rsms/inter](https://github.com/rsms/inter).

## Synthetic-data posture

Every value drawn into a generated document is fictional. Persons,
organizations, account numbers, and identifiers are invented; e-mail addresses
use the RFC 2606 reserved example domains. No production or real-world document is
included.

Nothing in this policy is legal advice.
