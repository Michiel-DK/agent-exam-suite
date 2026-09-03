You categorize bank and card transaction lines for a Belgian freelance AI consultant's
bookkeeping.

For the transaction below, determine:

- "category": one of "software" (SaaS, cloud, APIs), "hardware", "meals" (restaurants,
  client lunches), "travel" (transport, hotels, fuel), "telecom" (phone, internet),
  "office" (supplies, coworking), "marketing" (ads, domains, design), "other"
- "recurring": true if this is clearly a subscription or repeating charge
  (monthly/yearly SaaS, telecom plans), false otherwise

Respond with ONLY a JSON object, no other text:
{"category": "<category>", "recurring": <true|false>}
