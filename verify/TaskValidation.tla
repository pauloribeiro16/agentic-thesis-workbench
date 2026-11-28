--------------------------- MODULE TaskValidation ---------------------------
(***************************************************************************)
(* An agent task and the validation of its output (atw/tasks.py,           *)
(* TaskService.validate). The agent writes its output file (valid or not)  *)
(* as often as it likes; the author (or the agent) runs validate. Only a   *)
(* valid output takes effect (comments get proposals, change proposals are *)
(* created, applied changes are marked) — and only once.                   *)
(*                                                                         *)
(* Requirements: RF-TSK-04, RF-TSK-05.                                     *)
(***************************************************************************)
EXTENDS Naturals, Sequences, TLC

CONSTANTS
    DoneIsFinal,   \* TRUE after the fix: validating a task that is already done changes nothing
    MaxSteps

Actions == {"write-valid", "write-invalid", "validate"}
T0 == [status |-> "open", output |-> "none", effects |-> 0]

Step(t, x) ==
    CASE x = "write-valid" -> [t EXCEPT !.output = "valid"]
      [] x = "write-invalid" -> [t EXCEPT !.output = "invalid"]
      [] x = "validate" ->
           IF t.output = "none" \/ (DoneIsFinal /\ t.status = "done") THEN t
           ELSE IF t.output = "valid" THEN [t EXCEPT !.status = "done", !.effects = @ + 1]
           ELSE [t EXCEPT !.status = "invalid"]

RECURSIVE Run(_, _)
Run(t, xs) == IF xs = <<>> THEN t ELSE Run(Step(t, Head(xs)), Tail(xs))

VARIABLES t, n
vars == <<t, n>>
Init == t = T0 /\ n = 0
Next == n < MaxSteps /\ \E x \in Actions : t' = Step(t, x) /\ n' = n + 1
Spec == Init /\ [][Next]_vars

(* RF-TSK-04: an output takes effect at most once, however often it is validated *)
EffectsAtMostOnce == t.effects <= 1
(* RF-TSK-05: a task is done only if a valid output took effect; once done it stays done *)
DoneMeansEffect == t.status = "done" => t.effects = 1
DoneStaysDone == [][t.status = "done" => t'.status = "done"]_vars

Seqs(m) == UNION {[1..i -> Actions] : i \in 0..m}
Table == {<<xs, Run(T0, xs).status, Run(T0, xs).effects>> : xs \in Seqs(5)}
=============================================================================
