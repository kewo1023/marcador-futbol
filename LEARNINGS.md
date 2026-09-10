# What I learned building this

*[Versión en español](APRENDIZAJES.md)*

A football forecasting model that grades itself: it records predictions before
matches are played, ingests results, measures itself against the market, and
decides on its own whether to swap models.

This is the honest summary of what worked and what didn't. The second section is
longer than the first, and that isn't an accident of this project — it's what
happens when you actually measure.

---

## The thesis: build the scoreboard before the model

The instinct is to open a notebook, train a win/draw/loss classifier, and look at
accuracy. It comes out at 52% and there's no way to tell whether that's good,
bad, or luck.

Here the first two phases produced no model at all. They produced a
**scoreboard**: a table of immutable predictions, ingested results, and three
metrics. The first "model" evaluated was deliberately dumb — the historical base
rate.

**The thesis held, in a way I didn't expect.** Measuring the baselines before
modelling anything surfaced this:

| Reference | Log loss |
|---|---|
| Base rate | 1.0679 |
| Elo (a 20-line rating) | 0.9845 |
| Market (closing odds, vig removed) | 0.9556 |

The entire available headroom was 0.112 of log loss, and Elo already ate 74% of
it. Knowing that **before** writing the model changed what counted as success:
the bar wasn't the base rate, it was Elo, and only 0.029 was left to win.

Without that upfront measurement I'd have spent weeks celebrating beating the
base rate — which is trivial.

---

## What worked

**Time decay is almost the entire gain.** A Poisson model that treats a 2015
match the same as last week's scores 1.0086 — *worse* than Elo. What makes the
model competitive isn't the goal structure, it's forgetting. Measured
contribution: −0.0257 of log loss, conclusive.

**Regularisation, which wasn't in the plan.** The model was assigning
probabilities as low as **0.74%** to outcomes that then happened, and log loss
charges dearly for that. The cause: newly promoted teams carry almost no
effective weight under time decay, so their parameters were being estimated from
nothing. Shrinking them toward the league average raised the minimum emitted
probability to 4.52% and improved log loss by −0.0040 (p = 0.034).

**Writing the engine by hand.** Diagnosing the above required opening the
likelihood function and adding a term to it. With a closed library it wouldn't
have been possible. And in the new-markets phase, pointing the same engine at a
different column cost hours instead of weeks.

**The promotion gate.** A candidate replaces the production model only if it wins
on out-of-time validation *and* the difference survives a paired bootstrap. The
first real challenge was a rejection: a configuration that won on the tuning
block and lost on the gate block. Overfitting, caught exactly where it should be.

---

## What didn't work

**`rho`, half the model's name.** Dixon-Coles corrects the correlation between
low scores (0-0, 1-0, 1-1). Measured contribution: **−0.0002, p = 0.62.**
Nothing. The original paper is from 1997 using English data from 1992-95; that
dependency doesn't show up in the 2015-2026 Premier League. It was left
implemented and switchable rather than deleted, so it can be re-measured in
another league.

**Referees in the cards market.** The plan treated this as decisive, and the
spread between referees is real and large: 3.98 yellows per match for the
strictest against 2.63 for the most lenient, on a 3.47 average. But it **doesn't
predict**: a referee's history correlates **+0.0245** with the cards in the match
they're about to officiate, against +0.196 for the team model. Trusting it fully
makes log loss worse by 0.0509.

This is the most useful lesson in the project: *"obviously the referee matters"*
was true and would still have made the model worse. It matters in the past; it
doesn't carry forward.

**The raw model on corners.** It lost to simply saying "the league average" on
all four lines. The signal exists (0.119 correlation between predicted and actual
totals, comparable to goals) but it's weak against the noise: the model varies
with a standard deviation of 0.93 while reality varies by 3.39.

**Poisson for corners and shots.** Poisson requires variance = mean. That holds
for goals (residual dispersion 0.86), yellow cards (0.86) and shots on target
(0.99). It does not hold for corners (1.34) or total shots (1.46).

**Any attempt to turn the model into money.** Flat 1-unit stakes whenever the
model saw positive expected value, over 2,127 bets: ROI **−8.50%**, with the
entire interval below zero. Worse than betting every match blindly (−6.03%).

The value filter isn't merely useless, it's **actively harmful**: it selects the
matches where the model disagrees most with the price, which is exactly where the
market is right. Raising the EV threshold makes it worse, down to −16.55%. The
line movement confirms it independently: mean CLV −1.31%, the market drifts away
from the model's picks between taking the price and the close.

This is what the log loss predicted, which is why the expectation was written
down before looking: a model worse than the market cannot beat the market.

**All three attempts to close the home-win gap.** The diagnostic flagged that
front; three ideas were tried and the gate rejected all three.

A per-team home advantage turned out to be **pure noise**: the spread across
teams (6.71%) is what chance alone would produce (6.06%). Blending team strength
estimated from shots on target **shifted the level instead of discriminating** —
home probability rose to 48.7% and draws collapsed to 15.9% against a real 22.5%,
with correlation unchanged. And a recalibration layer using recent form did add
genuine discrimination (home-win correlation 0.3377 → 0.3502, surviving the
removal of its ability to shift levels) but only **−0.0026** of log loss,
indistinguishable from noise over 790 matches.

**Three of the four new markets.** Of goals over/under, corners, cards and shots
on target, only **cards** beats its base rate conclusively (p = 0.038 / 0.000 /
0.029). The other three show positive but noise-indistinguishable gains over 760
matches.

---

## Mistakes I made, and how they surfaced

This section exists because it's the part that says the most about how I work.

**I declared a win that didn't exist.** The first version of the backtest printed
*"BEATS Elo by 0.0018"*. The confidence interval crossed zero from end to end
(p = 0.55). What caught it was running a paired bootstrap instead of comparing
averages. **The fix wasn't deleting the line — it was moving the significance
test inside the script**, so it couldn't happen again. That same mechanism is now
the promotion gate.

**I invented a cause instead of investigating one.** Finding no Premier League
matches in the upcoming-fixtures file, I wrote that it was an international
break. I never verified it; it was false, and it ended up in five files. The real
reason is that the file covers a ~3-day window and the matchday fell outside it.
There were 18 matches from six other leagues in the same file — the evidence
against my explanation was on screen while I wrote it.

The bad part wasn't the fact. The invented explanation **made my own code look
correct**, which is precisely why it stopped me from asking the real question:
whether a 3-day window is enough to predict everything before kickoff. That
question produced the missed-match detector that now turns the workflow red when
there's a gap.

**An impossible number.** Measuring overdispersion, conditioning on the model
produced *higher* variance than the raw figure. That can't happen: explaining
part of the variation cannot increase it. The error was mine (I fitted with time
decay and evaluated against eleven years of matches). What gave it away wasn't
that it looked odd — it's that **the number could not be true**.

**Edits that failed silently.** Several scripted file edits didn't apply because
the search text lacked accents that the file had. One left the database schema
missing two columns: it worked locally thanks to a manual migration, but **a
fresh clone would have failed on ingest**. It surfaced by building a database
from scratch, which is what CI does on every run.

**I nearly accepted a price that didn't exist.** The first value analysis used
best-available odds across bookmakers and showed just 0.67% overround — too good.
**28.6% of matches had negative overround**, i.e. pure arbitrage. Real arbitrage
lasts seconds; appearing in one match in three revealed that this "price" was not
a simultaneous set but the maximum of each outcome taken separately across the
whole pre-match window. Both scenarios are reported: the model loses even at
impossible prices, which makes the conclusion firmer, not weaker.

**Data splits defined by index.** The test block was written as `SEASONS[6:]`.
Adding a new season silently moved it from 5 to 6 seasons, shifting numbers that
had already been reported. They're explicit now.

---

## And how it was solved: five leagues

The limit was solved the only way it could be — more data. Going from the
Premier League alone to the five big leagues multiplied the base fivefold:

| | One league | Five leagues |
|---|---|---|
| Matches | 4,210 | 19,909 |
| Gate block | 790 | 3,650 |
| Minimum detectable difference | 0.0060 | **0.0022** |

Each league is fitted separately; what gets pooled is the per-match losses.

**The recalibration layer, rejected with one league, passed the gate with
five:** −0.0033, CI [−0.0054, −0.0011], p = 0.003. It improves in four of the
five, which rules out a single-competition artifact. It's the project's first
promotion, after three rejections.

With an irony worth recording: **the exception is the Premier League**
(+0.0005) — precisely where the hypothesis was discovered. A lead found by
looking at one competition turned out to hold for the other four and not for
it. A reminder that a finding confirmed in the same place it was found is not
confirmed.

## The limit I hit at the end

The gate rejected the recalibration layer, and asking why produced the single
most useful finding in the project:

**With 790 matches, the gate can only call a difference of 0.0060 or larger
conclusive.** Validating the measured improvement (−0.0026) would take ~4,279
matches — eleven seasons of a single league.

The model's total distance to the market is 0.0230. Which means **only
improvements that close more than a quarter of that distance in one step are
demonstrable**. Every incremental gain is invisible — not because the gate is
miscalibrated (its conservatism is exactly what stops the system degrading) but
because one league doesn't supply enough matches.

That changes what comes next. Not a better model: **more data**. Four more major
leagues would multiply the gate block fivefold and bring improvements of this
size inside what can be verified. Switching leagues is a constant in
`config.py` — the Phase 0 decision to start with one league was right to get
going, and this is the point where it stops being right.

## Where the project stands

| | Log loss | vs Elo |
|---|---|---|
| Base rate | 1.0679 | — |
| Elo | 0.9845 | — |
| **Final model** | **0.9786** | −0.0059, **p = 0.147** |
| Market | 0.9556 | — |

**Against Elo it's a draw with an edge, not a win.** The model is ahead, but the
interval crosses zero over 1,900 matches. Against the market it loses by 0.0230,
and that one *is* conclusive.

The automated diagnostic says where the loss comes from: the model **beats the
market** on away wins (−0.0203) and on matches with a red card (−0.0116), and
gives it all back on **home wins** (+0.0386). That's the open front.

### Limitations worth stating

- **Five European leagues, all of similar standard.** The approach is tested on
  the Premier League, LaLiga, Bundesliga, Serie A and Ligue 1. Nothing
  demonstrates it transfers to competitions with less data, a different format
  (cups, playoffs) or very uneven levels.
- **Corners, cards and shots are measured without a ceiling.** The source
  publishes no odds for those markets, so I can tell whether the model adds
  something, not how far it is from what's achievable. That's a weaker
  measurement than the one for goals.
- **Phase 7 was measured on backtest, not on real bets.** No money was staked:
  it's a simulation using the historical prices the source publishes.
- **There is no live track record yet.** The system is built and verified
  end-to-end with the clock rolled back over real data, but it hasn't yet emitted
  its first batch of predictions on future matches. Until it does and accumulates
  ~100 matches, everything above is backtest.

---

## What I'd do differently

**Start with the paired bootstrap, not the average.** Nearly every decision in
this project came from comparing two numbers, and half those comparisons meant
nothing. Having the significance test from day one would have saved two false
conclusions.

**Measure the baselines before choosing the model.** Knowing Elo covered 74% of
the available headroom changed what counted as success. That number took two
phases to appear and should have been the first thing computed.

**Treat every surprising result as my own bug until proven otherwise.** All three
times something looked strange — the model losing on corners, the impossible
dispersion, the missing fixtures — the right response was to measure, not to
explain. Both times I explained first, I was wrong.
