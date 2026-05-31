# Food Price Compare — Setup Guide

## What this does
Tests whether we can pull real prices from Uber Eats, Deliveroo, and Just Eat
for the same restaurant. First step in building the comparison app.

## Step 1 — Install Node.js
If you don't have it: https://nodejs.org → download the LTS version.
Verify it's installed: open Terminal in VS Code and run `node --version`

## Step 2 — Get an Apify account + token
1. Go to https://apify.com and create a free account
2. Go to https://console.apify.com/account/integrations
3. Copy your **Personal API token**

## Step 3 — Set up your token
1. In this folder, find `.env.example`
2. Duplicate it and rename the copy to `.env`
3. Replace `your_apify_token_here` with your actual token

## Step 4 — Install dependencies
Open Terminal in VS Code (View → Terminal), navigate to this folder:

```bash
cd "food-price-compare"
npm install
```

## Step 5 — Run the tests

Test each platform individually first:

```bash
npm run test:ubereats    # Uber Eats
npm run test:deliveroo   # Deliveroo
npm run test:justeat     # Just Eat
```

Then run the full comparison:

```bash
npm run compare
```

## What to look for
- Does data come back? (restaurants + prices)
- What fields are available? (delivery fee, item prices, ETA)
- Are the price formats consistent enough to compare?

Output files (auto-generated):
- `uber-eats-output.json` — raw Uber Eats data
- `deliveroo-output.json` — raw Deliveroo data
- `just-eat-output.json` — raw Just Eat data
- `compare-output.json` — combined comparison

Open these in VS Code to see the full data shape.

## Costs (Apify free tier)
Apify gives you $5 free credit on signup — more than enough for testing.
Rough cost per run of `compare.js`: ~$0.05–0.15
