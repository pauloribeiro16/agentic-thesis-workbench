-------------------------- MODULE CommentLifecycle --------------------------
(***************************************************************************)
(* One comment from open to applied (atw/comments.py, CommentService).     *)
(*                                                                         *)
(*  author:      status open|resolved|wontfix (any time), accept           *)
(*               (addressed -> approved, seals the proposal)               *)
(*  agent:       propose (open|addressed -> addressed, through a validated *)
(*               review whose quote is in the text), tamper (edits the     *)
(*               stored proposal after approval: the seal no longer fits)  *)
(*  implementer: edit (puts the replacement in the text), apply            *)
(*               (approved and sealed -> applied, if the text shows it)    *)
(*                                                                         *)
(* The text is abstracted to `quoteIn`: the commented passage is still in  *)
(* the file. The replacement is in the file iff it is empty or the passage *)
(* was edited. `pq`: the stored proposal still quotes that passage (false  *)
(* after tampering). Accept needs it, so the author never seals a proposal *)
(* that does not anchor in the text. Requirements: RF-COM-03..08.          *)
(***************************************************************************)
EXTENDS Naturals, Sequences, TLC

CONSTANTS
    TextRule,   \* "replacement-present" (before the fix) | "passage-changed" (after)
    MaxSteps

Statuses == {"open", "addressed", "approved", "applied", "resolved", "wontfix"}
Actions == {[a |-> "status", s |-> s] : s \in {"open", "resolved", "wontfix"}}
           \cup {[a |-> "accept", s |-> ""], [a |-> "edit", s |-> ""], [a |-> "apply", s |-> ""],
                 [a |-> "tamper", s |-> ""]}
           \cup {[a |-> "propose", s |-> e] : e \in {"empty", "text"}}

C0 == [status |-> "open", prop |-> FALSE, sealed |-> FALSE, empty |-> FALSE, quoteIn |-> TRUE, pq |-> FALSE,
       setter |-> "author", sealedAtApply |-> FALSE, editedAtApply |-> FALSE]

ReplIn(c) == c.empty \/ ~c.quoteIn
\* as the code checks it: against the STORED quote — after tampering that quote is not in the file
TextShows(c) == IF TextRule = "replacement-present" THEN ReplIn(c) ELSE ReplIn(c) /\ (c.pq => ~c.quoteIn)

Step(c, x) ==
    CASE x.a = "status" -> [c EXCEPT !.status = x.s, !.setter = "author"]
      [] x.a = "accept" -> IF c.status = "addressed" /\ c.prop /\ c.pq /\ c.quoteIn
                           THEN [c EXCEPT !.status = "approved", !.sealed = TRUE, !.setter = "author"]
                           ELSE c
      [] x.a = "propose" -> IF c.status \in {"open", "addressed"} /\ c.quoteIn
                            THEN [c EXCEPT !.status = "addressed", !.prop = TRUE, !.sealed = FALSE, !.pq = TRUE,
                                           !.empty = (x.s = "empty"), !.setter = "agent"]
                            ELSE c
      [] x.a = "edit" -> IF c.prop /\ c.quoteIn THEN [c EXCEPT !.quoteIn = FALSE] ELSE c
      [] x.a = "apply" -> IF c.status = "approved" /\ c.sealed /\ TextShows(c)
                          THEN [c EXCEPT !.status = "applied", !.setter = "implementer",
                                         !.sealedAtApply = c.sealed, !.editedAtApply = ~c.quoteIn]
                          ELSE c
      [] x.a = "tamper" -> IF c.prop THEN [c EXCEPT !.sealed = FALSE, !.pq = FALSE] ELSE c

RECURSIVE Run(_, _)
Run(c, xs) == IF xs = <<>> THEN c ELSE Run(Step(c, Head(xs)), Tail(xs))

VARIABLES c, n
vars == <<c, n>>
Init == c = C0 /\ n = 0
Next == n < MaxSteps /\ \E x \in Actions : c' = Step(c, x) /\ n' = n + 1
Spec == Init /\ [][Next]_vars

TypeOK == c.status \in Statuses

(* RF-COM-03: only the author approves, resolves or rejects a comment *)
OnlyAuthorDecides == c.status \in {"approved", "resolved", "wontfix"} => c.setter = "author"
(* RF-COM-04: an agent can only bring a comment to "addressed" *)
AgentOnlyProposes == c.setter = "agent" => c.status = "addressed"
(* RF-COM-05: an approved comment carries the author's seal unless its proposal was tampered with *)
ApprovedIsSealedOrTampered == c.status = "approved" => c.prop
(* RF-COM-06: applied only what the author approved and sealed *)
AppliedWasSealed == c.status = "applied" => c.sealedAtApply /\ c.setter = "implementer"
(* RF-COM-07: "applied" means the text really changed — also for deletions (empty replacement) *)
AppliedMeansEdited == c.status = "applied" => c.editedAtApply

Seqs(k) == UNION {[1..i -> Actions] : i \in 0..k}
Table == {<<xs, Run(C0, xs).status, Run(C0, xs).sealed, Run(C0, xs).quoteIn>> : xs \in Seqs(4)}
=============================================================================
