-------------------------- MODULE ChangeLifecycle --------------------------
(***************************************************************************)
(* One change proposal (atw/changes.py, ChangeService) — a before/after    *)
(* edit not tied to a comment.                                             *)
(*                                                                         *)
(*  author:      decide pending|approved|rejected (approving seals it),    *)
(*               review kept|contested|undo once it is in the text,        *)
(*               register (records the decision in its dialogue thread)    *)
(*  agent:       tamper (edits the stored item: the seal no longer fits)   *)
(*  implementer: edit (puts the new text in the file), apply               *)
(*                                                                         *)
(* Requirements: RF-CHG-02..07.                                            *)
(***************************************************************************)
EXTENDS Naturals, Sequences, TLC

CONSTANTS
    ApproveNeedsAnchor,  \* TRUE after the fix: approving needs the old text exactly once in the file
    MaxSteps

Statuses == {"pending", "approved", "rejected", "applied"}
Actions == {[a |-> "decide", s |-> d] : d \in {"pending", "approved", "rejected"}}
           \cup {[a |-> "review", s |-> r] : r \in {"kept", "contested", "undo"}}
           \cup {[a |-> x, s |-> ""] : x \in {"register", "edit", "apply", "tamper"}}
           \cup {[a |-> "new", s |-> e] : e \in {"empty", "text"}}   \* which proposal the agent wrote

K0(e) == [status |-> "pending", decision |-> "none", before |-> "none", hasBefore |-> FALSE,
          registered |-> FALSE, sealed |-> FALSE, pq |-> TRUE, quoteIn |-> TRUE, empty |-> (e = "empty"),
          setter |-> "agent", sealedAtApply |-> FALSE, editedAtApply |-> FALSE]

Verdict(k) == IF k.status = "applied"
              THEN CASE k.decision = "kept" -> "approved" [] k.decision = "contested" -> "rejected"
                        [] OTHER -> "review"
              ELSE k.status

ReplIn(k) == k.empty \/ ~k.quoteIn
\* as the code checks it: against the STORED old text — after tampering that text is not in the file
TextShows(k) == ReplIn(k) /\ (k.pq => ~k.quoteIn)

Step(k, x) ==
    CASE x.a = "decide" ->
           IF ~k.registered /\ k.status # "applied"
              /\ (x.s = "approved" /\ ApproveNeedsAnchor => k.pq /\ k.quoteIn)
           THEN [k EXCEPT !.status = x.s, !.sealed = (x.s = "approved"), !.setter = "author"]
           ELSE k
      [] x.a = "review" ->
           IF ~k.registered /\ k.status = "applied"
           THEN IF x.s = "undo"
                THEN IF k.hasBefore THEN [k EXCEPT !.decision = k.before, !.hasBefore = FALSE] ELSE k
                ELSE [k EXCEPT !.before = IF k.hasBefore THEN k.before ELSE k.decision, !.hasBefore = TRUE,
                               !.decision = x.s]
           ELSE k
      [] x.a = "register" ->
           IF Verdict(k) \in {"approved", "rejected"} /\ ~k.registered THEN [k EXCEPT !.registered = TRUE] ELSE k
      [] x.a = "edit" -> IF k.quoteIn THEN [k EXCEPT !.quoteIn = FALSE] ELSE k
      [] x.a = "apply" ->
           IF k.status = "approved" /\ k.sealed /\ TextShows(k)
           THEN [k EXCEPT !.status = "applied", !.decision = "kept", !.setter = "implementer",
                          !.sealedAtApply = k.sealed, !.editedAtApply = ~k.quoteIn]
           ELSE k
      [] x.a = "tamper" -> [k EXCEPT !.sealed = FALSE, !.pq = FALSE]
      [] x.a = "new" -> k

RECURSIVE Run(_, _)
Run(k, xs) == IF xs = <<>> THEN k ELSE Run(Step(k, Head(xs)), Tail(xs))

VARIABLES k, n
vars == <<k, n>>
Init == \E e \in {"empty", "text"} : k = K0(e) /\ n = 0
Next == n < MaxSteps /\ \E x \in Actions : k' = Step(k, x) /\ n' = n + 1
Spec == Init /\ [][Next]_vars

TypeOK == k.status \in Statuses

(* RF-CHG-02: only the author approves or rejects a change *)
OnlyAuthorDecides == k.status \in {"approved", "rejected"} => k.setter = "author"
(* RF-CHG-03: a change reaches the text only after a sealed approval *)
AppliedWasSealed == k.status = "applied" => k.sealedAtApply /\ k.setter = "implementer"
(* RF-CHG-04: "applied" means the text really changed — deletions included *)
AppliedMeansEdited == k.status = "applied" => k.editedAtApply
(* RF-CHG-05: a registered decision is final: no later decide or review changes it *)
RegisteredIsFinal == [][k.registered => (k'.decision = k.decision \/ k'.status = "applied")
                                         /\ (k'.status = k.status \/ (k.status = "approved" /\ k'.status = "applied"))]_vars
(* RF-CHG-06: only decided changes are registered *)
RegisteredWasDecided == k.registered => Verdict(k) \in {"approved", "rejected"} \/ k.status = "applied"

\* conformance table: every proposal kind and every sequence of up to 4 actions
Seqs(m) == UNION {[1..i -> Actions \ {[a |-> "new", s |-> "empty"], [a |-> "new", s |-> "text"]}] : i \in 0..m}
Table == {<<e, xs, Run(K0(e), xs).status, Run(K0(e), xs).decision, Run(K0(e), xs).registered,
            Run(K0(e), xs).sealed, Run(K0(e), xs).quoteIn>> : e \in {"empty", "text"}, xs \in Seqs(4)}
=============================================================================
