# marcador-futbol

*[Versión en español](README.md)*

A football forecasting system that grades itself: it records predictions before
matches are played, ingests the results, measures itself against the market, and
**decides on its own** whether to swap models.

**The thesis:** you build the system that judges the model before you build the
model. Anything that "corrects itself" needs to know in which direction to
correct, and only a measurement system that already exists can tell it that.

**Five leagues:** Premier League, LaLiga, Bundesliga, Serie A and Ligue 1 —
19,909 matches.

**Live dashboard:** https://marcador-futbol-2rs4efqkkrvipztze7k5mr.streamlit.app/

**Live since 2026-09-10.** The first real batch — 43 matches across five
leagues, two markets — is in the ledger with its commit timestamp, hours before
kick-off. Everything before that date was backtest.

### Where to start reading

| If you want to… | Go to |
|---|---|
| Understand the system without reading anything else | **[PDF tutorial](docs/TUTORIAL.pdf)** — 9 pages, in Spanish |
| See what worked and what didn't, unvarnished | **[LEARNINGS.md](LEARNINGS.md)** |
| See the measured result | [The scoreboard](#the-scoreboard), below |
| Understand why the model can't degrade itself | [The promotion gate](#the-promotion-gate) |
| Read the engine | [`src/marcador/dixon_coles.py`](src/marcador/dixon_coles.py) |
| See how data leakage is prevented | [`src/marcador/db.py`](src/marcador/db.py) — triggers, not documentation |
| Audit the predictions without trusting anyone | [`ledger/`](ledger/) and `git log` |

Code comments and the full documentation set are in Spanish. This file and
[LEARNINGS.md](LEARNINGS.md) cover everything a reader needs.

### The three-line summary

The final model scores **0.9786** log loss on the Premier League backtest. Elo
scores 0.9845 and the market 0.9556. Against Elo the model is ahead, but the
confidence interval crosses zero (p = 0.147): **it's a draw with an edge, not a
win**, and it's reported that way. Against the market it loses, and that one is
conclusive.

Of four markets built on the same engine, with one league only **one** beat its
base rate demonstrably; with five leagues **all four** do. Yellow cards, the
strongest, is emitted live.

## Status

| Phase | What | State |
|---|---|---|
| F0 | Foundations and scope | ✅ |
| F1 | Data and the scoreboard | ✅ |
| F2 | Dixon-Coles engine | ✅ |
| F3 | Automated loop (GitHub Actions + dashboard) | ✅ |
| F4 | Retraining with a promotion gate | ✅ |
| F5 | New markets: corners, cards, shots | ✅ |
| F6 | Packaging and documentation | ✅ |
| F7 | Edge against the market (optional) | ✅ · no edge |

## The scoreboard

Walk-forward backtest on the Premier League. Eleven seasons split into 3 for
warm-up, 3 for validation (where hyperparameters are chosen) and **5 for test,
which are the only ones reported**. Choosing `xi` while looking at the same
seasons you later report on would be leakage — it doesn't enter through the
features, it enters through the decision of which hyperparameter to use.

| Model | Log loss ↓ | Brier ↓ | Accuracy | % of headroom covered |
|---|---|---|---|---|
| Base rate | 1.0679 | 0.6461 | 44.2% | — (the floor) |
| Plain Poisson | 1.0086 | 0.6021 | 50.7% | 52.8% |
| Elo | 0.9845 | 0.5871 | 54.3% | 74.3% |
| Poisson + time decay | 0.9829 | 0.5838 | 53.3% | 75.7% |
| Dixon-Coles (+ rho) | 0.9826 | 0.5837 | 53.3% | 75.9% |
| **Dixon-Coles + regularisation** | **0.9786** | **0.5823** | 53.2% | **79.5%** |
| Market (closing, vig removed) | 0.9556 | 0.5670 | 55.9% | — (the ceiling) |

Note the final model has *lower* accuracy than Elo and is still better. Accuracy
is shown as context and decides nothing — rule 5 of [CLAUDE.md](CLAUDE.md).

### What each piece contributed

Paired comparison on the same matches, 20,000 bootstrap resamples. Negative means
improvement.

| Change | Difference | 95% CI | Conclusive? |
|---|---|---|---|
| Time decay | −0.0257 | [−0.0355, −0.0156] | **yes** |
| `rho` low-score correction | −0.0002 | [−0.0012, +0.0007] | no |
| Regularisation | −0.0040 | [−0.0093, −0.0002] | **yes** |
| Final model − Elo | −0.0059 | [−0.0137, +0.0020] | no |
| Final model − market | +0.0230 | [+0.0151, +0.0309] | **yes** (market wins) |

**Time decay is the whole gain.** A Poisson model that treats a 2015 match the
same as last week's is *worse* than Elo. What makes the model competitive isn't
the goal structure — it's forgetting. The validation-chosen `xi = 0.002` is a
half-life of about 11 months.

**`rho` contributes nothing.** The low-score correction is half the model's name
and here it's dead weight: −0.0002, p = 0.62, with the fitted parameter sitting
at −0.004 where the 1997 paper reported values near −0.13. The dependence between
low scorelines that existed in 1992–95 English data doesn't show up in the
2015–2026 Premier League. It stays implemented and switchable.

**Against Elo it's a draw with an edge, not a win.** 0.0059 ahead, but the
interval crosses zero (p = 0.147). Over 1,730 matches that isn't enough to call
it better, and the script says so instead of announcing a victory.

### Why regularisation was needed

The model was emitting probabilities as low as **0.74%** on outcomes that then
happened, and log loss charges those cases dearly. The cause was newly promoted
teams: under time decay their effective weight is almost zero, so their
parameters were estimated on nothing and went to extremes. Regularisation pulls
teams with little data toward the league average and leaves the rest alone. The
minimum emitted probability went from 0.74% to **4.52%**.

## From one league to five, and the first promotion

The limit described further down — the gate couldn't validate improvements
smaller than 0.0060 on 790 matches — was solved the only way it could be:
**more data**.

| | One league | Five leagues |
|---|---|---|
| Matches in the database | 4,210 | **19,909** |
| Gate block | 790 | **3,650** |
| Minimum detectable difference | 0.0060 | **0.0022** |

Each league is fitted separately — the teams don't overlap, a joint fit would
need league effects — and what gets pooled is **the per-match losses**, which are
comparable: a log loss is a log loss wherever it comes from.

### The result: the recalibration layer passed the gate

The same layer that had been rejected with one league was resubmitted:

| League | n | Champion | Candidate | Diff. |
|---|---|---|---|---|
| Premier League | 790 | 1.0061 | 1.0066 | +0.0005 |
| LaLiga | 801 | 0.9753 | **0.9686** | −0.0068 |
| Bundesliga | 630 | 0.9997 | **0.9984** | −0.0013 |
| Serie A | 790 | 0.9774 | **0.9723** | −0.0050 |
| Ligue 1 | 639 | 0.9912 | **0.9880** | −0.0032 |
| **ALL** | **3650** | **0.9894** | **0.9862** | **−0.0033** |

**PROMOTED** — 95% CI [−0.0054, −0.0011], p = 0.003. Better in four of five
leagues, which rules out an artefact of one competition. It's the project's
**first promotion**, after three rejections — which is exactly the sign the gate
doesn't hand out titles for free.

With an irony worth recording: the exception is the Premier League (+0.0005),
which is precisely where the hypothesis was found. A clue found in one
competition turned out to work for the other four and not for it.

### What runs on five leagues and what doesn't

The **production loop** (ingest, predict, score) and the **gate** run on all
five. The historical analysis scripts — the F2 backtest, the diagnostic, the
markets and the edge study — stay on the Premier League: changing them would move
numbers already reported, and their value is documentary. Where a five-league
version matters, it lives in a separate script and a separate ledger file, so
the two tables can be read side by side.

## Attacking home wins, and the limit that appeared

The diagnostic said the model loses to the market mostly on home wins. That
front was attacked. **All three attempts were rejected by the gate, and the
third for a reason that redefines the project's ceiling.**

First, the problem was confirmed outside the block where it was found: on
2021/22–2023/24, seasons the diagnostic never saw, the home-win gap is +0.0333.
Not an artefact. And the cause was pinned down: **not level, discrimination.**
The model gives 43.6% mean home probability and the market 43.9% — the same. But
the correlation with the outcome is 0.3925 against 0.4325. It separates matches
worse.

**Attempt 1 — per-team home advantage: it's noise.** Between-team variation of
the home residual is 6.71%; what pure chance would produce given the match
counts is 6.06%. Fitting that would be fitting noise and calling it a model.

**Attempt 2 — strength estimated with shots on target: shifts, doesn't
discriminate.** Home-win log loss improved enormously (0.7345 → 0.6089) — and
it was a trap. Mean home probability rose from 43.6% to 48.7% while draws sank
from 23.0% to 15.9%, against a true 22.5%. Correlation didn't move. Total
−0.0008, p = 0.52. **It was moving mass, not separating matches.**

**Attempt 3 — recalibration on recent form: real, but tiny.** A logistic layer
correcting the three probabilities with rolling means of shots, shots on target,
corners and goals — the things a Poisson engine can't see, because it only
counts goals and a team that creates a lot without scoring looks identical to one
that creates nothing. The first version repeated attempt 2's error subtly. With
the ability to move the global level removed — no intercepts, weights only —
**the gain survived**: correlation with home wins 0.3377 → 0.3502, mean
probability unchanged. That's the proof it carries information. Total:
**−0.0026. Rejected, p = 0.409.**

### The limit this exposed

The gate didn't reject on a whim. With 790 matches it **can only call a
difference of 0.0060 or more conclusive**. Validating −0.0026 would need ~4,279
matches: eleven seasons of a single league.

And the model's total distance to the market is 0.0230. So **only improvements
that close more than a quarter of that distance in one go are provable**. Any
incremental advance is invisible to this gate — not because the gate is
miscalibrated, its conservatism is right, but because one league doesn't
provide enough matches.

**The project's next step isn't a better model: it's more data.** That is what
led to five leagues, above.

## Attacking draws: five candidates, five rejections, one lesson

With five leagues, the diagnostic left **one clue that got stronger**: the gap
against the market on matches that end in a draw went from +0.0103 (Premier) to
+0.0207, conclusive. `scripts/13_draws.py` attacked it with the same discipline
as home wins, and now with the 3,650-match gate that attempt didn't have.

**First, confirm.** On 2021/22–2023/24 — seasons the diagnostic didn't look at —
the draw gap is +0.0176, CI [+0.0108, +0.0243]. Real.

**Second, level or discrimination?** Neither clearly, and that was already a
signal:

| | Actual draws | Model p(D) | Market p(D) | Model corr. | Market corr. |
|---|---|---|---|---|---|
| Five leagues | 25.5% | 24.6% | 25.0% | 0.114 | 0.121 |

The model puts 0.9 points less draw than occurs (the market, 0.5 less) and
discriminates barely worse. But per league the picture differs: **Serie A**
underestimates the draw by 2.8 points while the Premier League nails it, and
**Bundesliga** discriminates much worse than the market (0.098 vs 0.135) while
the others nearly match it. Five different ailments under one symptom.

**Third, the candidates**, tuned on 2021/22–2023/24 and judged on 2024/25–2026/27
against the full champion (engine + layer):

| Candidate | What it is | Diff. | 95% CI | Draw gap afterwards |
|---|---|---|---|---|
| A · draw shift | one parameter raising the draw logit | −0.0002 | [−0.0008, +0.0005] | **−0.0055** |
| B · shape | two features derived from the engine (parity, draw logit) | −0.0004 | [−0.0015, +0.0006] | +0.0360 |
| C · A + B | | −0.0007 | [−0.0019, +0.0005] | +0.0018 |
| D · per-league shift | five parameters, one per league | **+0.0002** | [−0.0009, +0.0013] | −0.0073 |
| E · D + B | | −0.0005 | [−0.0019, +0.0009] | −0.0005 |

**All five rejected.** Row A is the lesson: **it closes the draw gap from
+0.0300 to −0.0055 — the model starts beating the market on draws — and the
total moves by 0.0002.** What it gains on draws it gives back on home and away
wins. It's attempt 2 on home wins in reverse: moving mass, not separating
matches. D, the best-looking on the tuning block, outright loses on the gate:
the +0.15 Serie A chose on 2021/22–2023/24 didn't hold on 2024/25–2026/27. Five
parameters instead of one, and the first to overfit.

**The lesson.** The draw gap wasn't an inefficiency that could be closed by
reassigning probability; it was the *symptom* of the model knowing slightly less
than the market about everything, and the draw — almost always the least likely
outcome — is where knowing less costs the most in log loss. Even the market
discriminates draws poorly (0.121). Closing that front needs information that
predicts draws, not a calibration lever. All five challenges are in
`ledger/challenges.csv`, with their intervals.

## Is there real edge against the market? (Phase 7)

**No.** And *how* there isn't is more interesting than the headline.

> This is analysis, not betting advice. It measures whether the model's
> probabilities carry information the price doesn't already have.

The expectation was set in advance: the model loses to the market by 0.0230 log
loss, conclusively. A model worse than the market cannot systematically beat it.
It was measured anyway, because measuring isn't the same as assuming.

Flat 1-unit stakes whenever the model sees positive expected value, across the 5
test seasons, settled on actual results:

| Strategy (average odds, realistic scenario) | Bets | ROI | 95% CI |
|---|---|---|---|
| EV > 0% | 2127 | **−8.50%** | [−15.86%, −0.87%] |
| EV > 2% | 1889 | −10.11% | [−17.78%, −2.19%] |
| EV > 5% | 1586 | −12.03% | [−20.71%, −3.19%] |
| EV > 10% | 1153 | −16.55% | [−26.69%, −5.95%] |
| *control: bet everything, no filter* | 5700 | *−6.03%* | *[−10.12%, −1.85%]* |

**The value filter destroys money.** It isn't merely useless: betting the model
(−8.50%) is *worse* than betting every match blindly (−6.03%). The filter selects
precisely the matches where the model disagrees most with the price — and there,
the market is right. **Tightening the filter makes it worse**, from −8.50% to
−16.55%. **The line moves against us**: mean closing-line value is −1.31%.

A trap worth flagging: the first pass used best-available odds and showed only
0.67% overround. Too good — **28.6% of matches showed negative overround, i.e.
pure arbitrage**. Real arbitrage lasts seconds; appearing in one match in three
means those aren't simultaneously available prices. Both scenarios are reported
on purpose: the model loses even at impossibly favourable prices.

The Phase 4 diagnostic had found the model beats the market on away wins. Tested
as a strategy on seasons the diagnostic never saw: ROI −7.62%, CI [−23.73%,
+9.85%]. And — see below — with five leagues that away-win advantage turned out
not to exist at all.

## Four markets on one engine

Switching markets means switching which column the two counts come from. The
engine doesn't know whether it's counting goals, corners, cards or shots. That
was the argument for writing Dixon-Coles by hand in F2, and this is where it
pays off — **with two caveats that only appear once you measure.**

**Poisson isn't enough everywhere.** Residual dispersion over 790 matches, with
team strength already accounted for: goals 0.86, cards 0.86, shots on target
0.99 — fine. Corners 1.34 and total shots 1.46 — not fine. For those two the
predictive distribution becomes negative binomial; the mean is still estimated by
the same engine. One parameter, not a redesign.

**The raw model lost to the base rate on corners.** The signal exists
(correlation 0.119 between predicted and actual totals, comparable to goals) but
it's weak against the noise. Shrinking toward the base — `p = w·model +
(1−w)·base`, with `w` chosen per market on the tuning block — fixes it, and the
optimal `w` measures how much the model can be trusted in that market.

**The referee, which the plan assumed decisive for cards, doesn't predict.** The
spread between referees is real (3.98 yellows per match at one end, 2.63 at the
other), but a referee's history correlates **+0.0245** with the cards in the
match they're about to officiate, against +0.196 for the team model. Trusting it
fully worsens log loss by 0.0509. It matters in the past; it doesn't project.

### The result on one league, and what five leagues said

On the Premier League, 2024/25–2025/26 with `w` chosen on 2021/22–2023/24:

| Market | Beats its base rate? | p |
|---|---|---|
| **Cards 2.5 / 3.5 / 4.5** | **Yes, all three** | 0.038 / 0.000 / 0.029 |
| Corners (4 lines) | Positive, not conclusive | 0.12 – 0.94 |
| Goals over/under (3 lines) | Positive, not conclusive | 0.39 – 0.59 |
| Shots on target (3 lines) | Positive, not conclusive | 0.16 – 0.76 |

`scripts/12_markets_multi.py` repeats the measurement on all five leagues
(~3,500 matches in the test block instead of 760) and writes
`ledger/markets_multi.csv`. **All four markets beat the base rate**, every line
with p < 0.001:

| Market | Best line | Beats base by | 95% CI |
|---|---|---|---|
| Yellow cards | 3.5 | +0.0278 | [+0.0221, +0.0335] |
| Shots on target | 9.5 | +0.0213 | [+0.0150, +0.0276] |
| Goals | 3.5 | +0.0116 | [+0.0066, +0.0166] |
| Corners | 8.5 | +0.0095 | [+0.0052, +0.0137] |

Rule 6's corollary for the third time in the project: the one-league "not
conclusive" results didn't say the model added nothing on goals, corners and
shots; they said 760 matches weren't enough to see it.

**The ceiling, where there is one.** The source publishes closing odds for 1X2
and over/under 2.5 goals only. Corners, cards and shots are measured **against
the base rate alone**: you learn whether the model adds something, not how far it
is from what's achievable. That's a weaker measurement and it isn't treated as
equivalent.

## The promotion gate

**The rule, in one line: the champion keeps the title unless it is beaten
conclusively. A tie goes to the champion.**

Every Monday a new configuration is searched for on a tuning block and put up
against the champion on three seasons **neither of them has seen**. Both are
refitted with the same procedure: comparing the champion as-is against a
freshly-trained challenger would always favour the challenger for having newer
parameters.

The decision uses a paired bootstrap, not a comparison of averages. The reason is
documented in this repo's own history: an early version declared the model "beats
Elo by 0.0018" and it was noise. A gate comparing averages would promote every
time chance handed over a tenth of an edge — and since promotion compounds, the
system would degrade on imaginary improvements. Which is exactly what this phase
exists to prevent.

The gate's record: three rejections, one promotion (the recalibration layer,
on five leagues), and five more rejections from the draws attack. Rejections are
shown on the dashboard because they're the proof the gate does something.

The production model lives in `ledger/champion.json`, **not in the code**. If it
were a Python constant, promoting would require a human to edit a `.py` — the
system wouldn't be correcting itself, it would be asking permission.

## Where the model loses

`scripts/07_diagnose.py` segments the error against the market and writes
`ledger/diagnostics.csv`. It compares against the market rather than against a
bare number because a high log loss in a segment may just be a hard segment;
what matters is how much is lost where the market faces the same difficulty.

On the Premier League, 2024/25–2026/27, the total gap is +0.0161, split as:

| Segment | Gap | Contributes |
|---|---|---|
| Home win | +0.0386 | **+0.0171** |
| Draw | +0.0254 | +0.0064 |
| Away win | −0.0203 | −0.0066 (model **wins**) |
| With a newly promoted team | +0.0100 | +0.0029 |
| With a red card | −0.0116 | −0.0013 (model **wins**) |

### Those two advantages don't exist

`scripts/11_diagnose_multi.py` repeats the diagnostic on all five leagues and
puts each segment through the same paired bootstrap the gate uses. It writes
`ledger/diagnostics_multi.csv` and **doesn't modify anything above**: the
one-league table is left as published.

The sample goes from 790 matches with closing odds to **3,650**, and both
"advantages" fall over:

| Segment | 1 league | 5 leagues | |
|---|---|---|---|
| Away win | −0.0114 | +0.0053 | flips, and is no longer distinguishable from zero |
| With a red card | −0.0039 | +0.0195 | flips, and is now demonstrable |
| Draw | +0.0103 | +0.0207 | confirmed, and doubled |
| Home win | +0.0410 | +0.0304 | confirmed |

Neither was a clue: it was the luck of which season a single league happened to
draw. The away-win one had become **the hypothesis Phase 7 went out to test**.

What remains after widening is a less comfortable and more useful result: **18 of
20 segments lose to the market with a demonstrable gap, and the split is even
across the five leagues** (+0.0161 in the Premier League to +0.0299 in the
Bundesliga, all conclusive). There is no pocket to attack. The gap belongs to the
model, not to a segment or a competition — a conclusion that 790 matches
couldn't support.

## The live loop

Three GitHub Actions workflows run on a schedule:

| Workflow | When | What |
|---|---|---|
| `score.yml` | 03:00 UTC daily | Ingests results, matches them to predictions, recomputes the scoreboard |
| `predict.yml` | every 4 h (01, 05, 09, 13, 17, 21 UTC) | Downloads upcoming fixtures, fits the model, emits predictions |
| `retrain.yml` | Mondays 06:00 UTC | Searches for a challenger, runs the gate, diagnoses where it fails |

### Source health stays in the ledger

Since 2026-09-11, every `04_predict.py` run leaves one row per league in
`ledger/source_health.csv`: matches in the window, how many without a confirmed
time, the file's last date, how long it had gone without regenerating, and any
download error or unknown team name. Until then all of that lived only in
Actions logs, which expire; "how often was the source wrong?" had no answer
with data. It costs one commit per run even with no new prediction (the
message says "salud de la fuente"), and that's the price of judging the new
source against the old with a series rather than an anecdote.

### "0 matches played" with four matches already over

On the morning of 2026-09-12 the dashboard said "Played: 0" with Friday's four
matches already finished. Nothing was broken: `score.yml` had run, re-downloaded
the season, and the results source hadn't regenerated its file since Monday
(`Last-Modified` 09-07, checked by hand). The results source doesn't publish in
real time, and the scoreboard can only match what it brings.

It was the same blind spot as 09-10, now on the results side: the "0" didn't
distinguish "nothing was played" from "it was played and the source hasn't
published it". Closed in two parts:

- The dashboard counts **predicted matches whose kickoff has passed and still
  have no result**, using the time in `fixtures.csv` (kickoff + 2 h) rather
  than the results source, which is precisely the one that can lag. Shown next
  to "Played", listed apart from the upcoming ones.
- Every `05_score.py` run leaves one row per league in
  `ledger/results_health.csv`: matches with a result in the file, the last
  date it reaches, how long it had gone without regenerating, and how many
  matches are waiting. That's the series that answers "how long does the
  source take to publish?", at one commit per day even with no results
  ("salud de resultados").

A "refresh" button in the dashboard was ruled out: it wouldn't fix anything
(the source would still lack the matches), the app is public and the button
would need a GitHub token, and only the runner writes to the ledger. The
button that does exist is **Run workflow** in Actions — and today it wouldn't
do anything either.

### `kickoff_utc` said UTC and was UK time

The history source doesn't document the time zone of its `Time` column. It was
measured against the fixtures source's UTC on 144 already-played matches across
the five leagues: **exactly +1 hour in all 144**. It's UK time — BST in summer,
GMT in winter — not UTC and not each country's local time (Spain or Italy would
have given +2). Ingest now converts with `Europe/London → UTC`, a real time zone
rather than a fixed offset, so the clock change doesn't break it twice a year.
`match_date` is untouched: it's the source's date and forms the `match_id`.
Verified after re-ingesting: 144 of 144 at zero.

### Where predictions live, and why it matters

In `ledger/`, as plain versioned text — not in the database, which is gitignored
and destroyed with the Actions runner at the end of each job. The commit date of
each batch is external proof the prediction existed before the match; stronger
than a `created_at` column the system writes itself. The dashboard reads
**only the ledger**, never the local database: if it needed the database,
nobody outside could reproduce what it shows.

### The fixtures source, and the blind spot it had

Upcoming fixtures originally came from the same source as the history, as a
single file covering ~3 days that the source regenerates when it likes. On
2026-09-10 that file had been frozen for **49 hours**, covered up to the 10th,
and the five leagues' matchday started on the 11th. Three runs finished green
saying "no matches to predict" — **the same message as a day with no football.**
The system couldn't tell "nobody's playing" from "my source is stuck".

Two fixes, the same day. First, `download_fixtures()` keeps the response's
`Last-Modified` and the log always reports the file's age, its leagues and its
date range; without a `Last-Modified` header the file is assumed stale, the same
fail-closed logic the pre-commit guard uses. Second, and because the detector
only turns a silent failure into a visible one, **the fixtures source changed**:
fixturedownload.com, one CSV per league with the full season and kick-off times
in UTC. The history, results and closing odds still come from
football-data.co.uk — that doesn't change, and it's what forces the next point.

**Team names are the real cost of the switch.** The `match_id` is built from
the date and the two team names, and the result arrives from football-data.co.uk
with *its* names: `Sevilla`, `Ath Bilbao`, `Man United`. A fixture written as
`Sevilla FC` would have a different id, never connect to its result, and under
rule 3 couldn't be corrected. `src/marcador/aliases.py` translates all 96 teams
into the canonical vocabulary **before** the id is built. A name the table
doesn't know **skips the match with a warning** — never guessed, because a wrong
id is an orphaned, immutable prediction — and `05_score.py` reports it in
`missed.csv` when it's played. Checked on 99 already-played matches: the new
source's UTC date matches football-data.co.uk's in all 99.

**A full season in view forced a forward cap.** Without one, `04_predict.py`
would have emitted 1,606 predictions at once — a May match predicted with the
September model, and since a written prediction is never replaced, that's the
one that would count. Now only matches within `FIXTURES_LOOKAHEAD_DAYS` (3)
whose kick-off hasn't passed are predicted. Each match is predicted as close to
kick-off as possible, not as early as possible.

**What couldn't be verified.** fixturedownload.com publishes no terms of use
(only `/privacy`) and doesn't say where its data comes from. It's used as a
bridge, behind a provider layer (`fixtures.py`) designed so that switching to an
API with explicit terms means replacing one function and the alias table.

### The market in the ledger

`results.csv` stores, with each result, the **closing-odds implied probability**
(bookmaker average, vig removed) — a derived value, not raw odds. That's what
lets the dashboard compare model against market match by match: how much
probability each put on what happened, and the difference. Summed over hundreds
of matches, that column is the live log loss at the top of the page. `05_score`
evaluates the market on exactly the matches the model has complete with odds,
under the same name the backtest uses, so "test" and "live" read side by side.

### The live over/under markets: cards, goals 2.5 and shots on target

Of the four markets, cards has the largest gain over the base rate, so it's the
one emitted live. Three things it does differently from 1X2:

- **It signs with its own name** (`dc-xi0020-reg002-norho+w-5l`), not the
  champion's. Neither `rho` nor the recalibration layer apply to cards; calling
  it the same would claim it passed a gate that doesn't exist.
- **The reference is emitted as a model too.** There are no closing odds for
  cards, so there's no market ceiling. What there is is the league's base rate —
  how many matches go over 3.5 yellows — and the loop writes it into the ledger
  as `base-freq-v1` with its own rows. `05_score.py` evaluates it with the same
  code as any model, and the dashboard can say "model vs base, same N matches"
  without a side calculation nobody can audit from the ledger.
- **The shrinkage weight `w` was re-tuned on five leagues the same day it went
  live, and it changed.** The one-league values (0.9 / 0.8 / 0.8) came from the
  Premier League; re-tuned per league, the Premier League chose exactly those
  again and the other four chose between 0.3 and 0.7. The inherited `w` wasn't
  "the market's", it was the only league that had been looked at, and it
  over-trusted the model elsewhere. Five-league values: **0.7 / 0.6 / 0.6**. The
  first 43 predictions went out with the old `w` and are immutable; since then
  the new version is emitted, and `05_score` evaluates both.

**Goals over/under 2.5 is emitted since 2026-09-11, for a different reason than
cards:** it's the only new market with closing odds in the source. Against the
base rate any decent model wins; against the market is the real test, and on the
Premier League the model lost by 0.0038. `results.csv` stores
`market_o25`/`market_u25` (closing implied probability, vig removed) and the live
scoreboard evaluates the market on the same matches, as with 1X2. Only the 2.5
line, deliberately: 1.5 and 3.5 have no odds and would only be measured against
the base, which cards already does. It signs as
`dc-xi0020-reg002-rho+goles-w-5l` — with rho, since goals use it, and with the
market name in the suffix because the slug would otherwise look dangerously like
the 1X2 champion's. `w` = 0.7, the five-league value.

**Shots on target is emitted since 2026-09-11** (`dc-xi0020-reg002-norho+sot-w-5l`,
lines 7.5 / 8.5 / 9.5, `w` = 0.6 / 0.7 / 0.7 from five leagues). It's the
second-largest gain over the base rate; with no odds in the source, it's
measured against the base alone. `results.csv` stores `sot`, the match total.
With this, all the Phase 5 markets that beat the base on five leagues are live
except corners, the weakest signal.

### On the Streamlit Cloud deployment

Every push to `main` redeploys on its own, but **without restarting the Python
process**: modules in `src/` that were already imported stay in memory at their
previous version. A push that adds a new module, or changes what a module
exports, breaks with an `ImportError` until **Reboot app** is clicked under
"Manage app". It happened on 2026-09-10 with `live_markets.py`; a clean clone
imported without a problem.

## How it's built, one line per piece

- **Raw data never enters the repo.** `data/` is gitignored; what's published is
  predictions and derived metrics.
- **Predictions are immutable**, and not by discipline: the database aborts any
  `UPDATE` or `DELETE` on them with a trigger.
- **No feature uses information from the future**, also enforced by the database:
  a prediction whose information cutoff post-dates the match is rejected.
- **Every backtest is walk-forward**, grouped by date so two matches on the same
  day can't leak into each other.
- **No comparison between models is made on averages**: they all go through a
  paired bootstrap, because a 0.002 log-loss difference over 1,700 matches sits
  comfortably inside the noise.
- **The production model lives in a versioned file, not in code**, which is what
  lets the gate promote without human intervention.
- **The dashboard shows kick-off times in the viewer's browser time zone.** No
  time zone is written anywhere in the code; the ledger stores UTC and each
  reader sees their own.

## Running it

Requires Python 3.11+. Phase 1 runs on the standard library alone.

```bash
python3 scripts/01_ingest.py     # download historical CSVs -> data/marcador.sqlite
python3 scripts/02_baseline.py   # baseline predictions and the scoreboard

python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python scripts/03_dixon_coles.py         # fit, backtest, compare
./.venv/bin/python scripts/04_predict.py --dry-run   # what it would predict today
./.venv/bin/python scripts/05_score.py               # ingest results and score
./.venv/bin/python scripts/06_retrain.py --dry-run   # what the gate would decide
./.venv/bin/python scripts/07_diagnose.py            # where it loses to the market
./.venv/bin/python scripts/08_markets.py             # the four markets
./.venv/bin/python scripts/11_diagnose_multi.py      # the diagnostic on 5 leagues, with intervals
./.venv/bin/python scripts/12_markets_multi.py       # the 4 markets on 5 leagues, re-tunes w
./.venv/bin/python scripts/13_draws.py --dry-run     # the draws attack, against the gate
./.venv/bin/streamlit run dashboard/app.py           # dashboard on localhost:8501
```

The first run downloads ~1.6 MB from the source and takes under a minute.

## Data sources

**History, results and odds:** [football-data.co.uk](https://football-data.co.uk)
— free per-season, per-league CSVs with results, corners, cards, shots, shots on
target, referee and closing odds from several bookmakers.

**Upcoming fixtures:** [fixturedownload.com](https://fixturedownload.com) — one
CSV per league with the full season and UTC kick-off times. Since 2026-09-10;
before that they came from football-data.co.uk's `fixtures.csv`, a ~3-day
snapshot regenerated at the source's discretion. Team names are translated in
`aliases.py`.

## Licence

MIT for the code — see [LICENSE](LICENSE). The data belongs to its respective
sources and is not redistributed here.
