# Private Wire Workflow

## Primary queue

Use the `Batch 2 account screening` tab as the working account queue. Every account should have:

- account fit fields
- bankability fields
- site screening status
- contact enrichment status
- outreach status
- next action

## Workflow order

1. Confirm the target clears the `> GBP 1bn revenue` threshold.
2. Determine bankability.
3. If bankable or review-worthy, screen UK sites.
4. Send strong site candidates to Jonathan in `Batch 2 site screening`.
5. Enrich contacts.
6. Prepare outreach actions and logging.

## Bankability rules

- If an external credit rating exists, pass only at `BBB-` or above.
- If no rating exists, use Companies House-based proxies.
- Escalate to `Needs review` when:
  - accounts are stale
  - the group structure is complex
  - critical financial fields are missing
  - the subsidiary looks weak but the parent may support the deal

### Minimum account output

- company name
- legal or parent entity used
- rating status
- accounts source
- profitability notes
- leverage notes
- interest coverage notes
- final verdict
- confidence notes

## Site screening rules

- Only work sites for `Bankable` or `Needs review` accounts.
- Focus on sites at or above `10,000 sqm`.
- Keep the output to the best `1-3` candidates.
- Exclude land that is obviously too urban, too constrained, or above `Grade 3b`.

### Minimum site output

- account name
- site name
- parcel id
- site size estimate
- buildability notes
- grade
- suitability rationale
- Jonathan qualification

## Contact enrichment

Priority roles:

- Energy Director
- Sustainability Director
- Indirect Sourcing
- Procurement Manager
- Site Manager

Target about 5 contacts per account. Prefer decision-makers and deduplicate aggressively.

## Salesforce and outreach

For outreach-ready accounts:

- create or confirm the account in Salesforce
- add contacts
- assign the `Cold outreach cadence - English`
- prepare the draft email

Positive outcomes:

- log meeting date, name, role, and site pitched
- send a Slack-ready update to the UK origination channel

Negative outcomes:

- close the conversation
- stop the automatic email flow

## QA expectations

- every feature has a test plan
- every bug fix gets a regression test
- simplify logic before expanding automation
- keep manual copy-paste to a minimum
