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

**Three of the four new markets — with one league.** Of goals over/under,
corners, cards and shots on target, only **cards** beat its base rate
conclusively over 760 matches (p = 0.038 / 0.000 / 0.029). The other three
showed positive but noise-indistinguishable gains. **With five leagues all four
beat it**, p < 0.001 on all thirteen lines. It wasn't that they added nothing;
it was that there wasn't enough sample to see it. See below.

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

**A "where it loses most" that meant nothing.** The first five-league
diagnostic took the group contributing most to the gap across ALL cuts, and
returned "no red card". That's 3,053 of 3,650 matches: in an unbalanced cut the
big side wins by construction. Each cut is a different partition of the same
set, and "contributes" only compares within one. What gave it away was that the
answer was useless, not that it was false.

**An inherited parameter that looked general.** The cards shrinkage weight went
live with Phase 5's values without re-tuning, on the argument that they were one
grid step apart. Re-tuned per league that same afternoon: the Premier League
chose exactly those, the other four chose less. The argument was true and it
wasn't enough. Changed under a new version; the first 43 predictions with the old
weight stay, and the scoreboard evaluates both.

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

## What happened on going live, in a single day

On 2026-09-10 the system emitted its first real batch. What that day taught fits
in six points, and four of them are the same lesson.

**Rule 6's corollary, three times over.** "A rejection for lack of power doesn't
say the candidate is useless." Repeating on five leagues three analyses that had
been done on one changed three published conclusions: two "advantages" from the
diagnostic turned out not to exist (they were the luck of which season one league
drew), the three "not conclusive" markets turned out to beat the base rate, and
the shrinkage weight for cards that Phase 5 had chosen turned out to be the one
league's own — the Premier League chose it again exactly; the other four chose
between 0.3 and 0.7. **A finding about one league is not a finding about
football.** And one of those false advantages had become the hypothesis Phase 7
went out to test.

**Moving mass, in reverse.** Attempt 2 on home wins raised home probability at
the expense of draws. Attacking draws with a one-parameter shift did the mirror
image: the draw gap closed completely (+0.0300 → −0.0055, the model starts
beating the market there) and the total moved by 0.0002. What it gains on draws
it gives back on home and away wins. Five candidates, five rejections, and the
five-parameter one — best on the tuning block — lost on the gate. **A gap in one
segment is a symptom, not a cause:** the model knows slightly less about
everything, and the least likely outcome is where knowing less costs the most.

**The system had a blind spot at its own input.** The upcoming-fixtures file
was a ~3-day snapshot the source regenerates when it likes. It had been frozen
for 49 hours with the matchday the next day, and three loop runs finished green
saying "no matches" — the same message as a day with no football. A project
whose thesis is that the measurement system comes before the model wasn't
measuring the freshness of its source. The source was switched the same day, and
the real cost wasn't the API: it was 96 team names, because the `match_id`
carries the name and a prediction with the wrong id is orphaned and immutable.

**A bug latent since Phase 3 that only surfaced with real data.** The first run
with matches to predict failed with `FOREIGN KEY constraint failed`: the
prediction script never registered the model in the versions table. It was
hidden by two things covering for each other: dry runs insert nothing, and until
that day there had never been anything to insert. **"Verified end-to-end" with
the clock rolled back is not the same as verified with tomorrow's match.**

**A full season in view demands a cap.** With the new source, the first test
emitted 1,606 predictions at once: a May match with the September model. With
the 3-day snapshot the cap wasn't needed, so it didn't exist. Since a written
prediction is never replaced, that one would have counted. Each match is
predicted as close to kick-off as possible, not as early as possible.

**The reference is emitted as a model too.** There are no odds for cards, so the
only yardstick is the league's base rate. Instead of computing it on the side,
the loop writes it into the ledger as a model with its own rows. The scoreboard
evaluates it with the same code, and the dashboard says "model vs base" from the
ledger alone, auditable by anyone.

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

The one-league diagnostic said the model **beat the market** on away wins
(−0.0203) and on matches with a red card (−0.0116). On five leagues **neither
exists**: the away-win one flips (+0.0053) and is no longer distinguishable from
zero; the red-card one flips (+0.0195) and is demonstrable. What's left is less
comfortable: 18 of 20 segments lose with a demonstrable gap, evenly across the
five leagues. There is no pocket to attack. The gap belongs to the model.

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
- **The live track record started on 2026-09-10.** First batch: 43 matches,
  five leagues, two markets, emitted hours ahead with the commit date as proof.
  Until it accumulates ~100 matches, everything above is still backtest, and the
  first real matchday is what will say whether aliases, dates and market line up
  in production and not just in tests.

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
