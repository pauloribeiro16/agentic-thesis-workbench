---------------------------- MODULE Governance ----------------------------
(***************************************************************************)
(* Who may change the state of a dialogue question (atw/dialogue.py,       *)
(* DialogueService.parse_thread / _apply).                                 *)
(*                                                                         *)
(* A thread is a sequence of writes. An agent turn writes a state in its   *)
(* consolidated table; the moderator (the author) writes a decision block, *)
(* sealed with an HMAC of the author's key or not. Step is the code's rule *)
(* for one write; the spec explores every sequence of writes.              *)
(*                                                                         *)
(* Requirements: RF-GOV-01..06 (verify/requirements.toml).                 *)
(***************************************************************************)
EXTENDS Naturals, Sequences, TLC

CONSTANTS
    Signing,     \* [agents] sign_decisions
    AuthorOnly,  \* states only a sealed author decision may set (AUTHOR_ONLY_STATES)
    MaxWrites    \* bound on the length of a thread

States == {"OPEN", "AGENT_CONSENSUS", "AGENT_DEADLOCK", "AUTHOR_RESERVED",
           "SINGLE_PROPOSAL", "APPROVED", "REJECTED"}
\* the states a moderator decision block can carry (append_decision labels)
ModStates == {"APPROVED", "REJECTED", "OPEN", "AUTHOR_RESERVED"}

Writes == {[kind |-> "agent", st |-> s, sealed |-> FALSE] : s \in States}
          \cup {[kind |-> "moderator", st |-> s, sealed |-> b] : s \in ModStates, b \in BOOLEAN}

Q0 == [state |-> "OPEN", auth |-> FALSE, claims |-> 0, setter |-> "none"]

(* One write, exactly as DialogueService._apply. `setter` is a ghost field:  *)
(* who set the current state (the code does not store it).                 *)
Step(q, w) ==
    LET authority == w.kind = "moderator" /\ (w.sealed \/ ~Signing)
        authorOnly == w.st \in AuthorOnly
    IN  IF w.kind = "agent" /\ authorOnly /\ q.auth /\ q.state = w.st THEN q
        ELSE IF w.kind = "agent" /\ authorOnly THEN [q EXCEPT !.claims = @ + 1]
        ELSE IF w.kind = "moderator" /\ ~authority THEN [q EXCEPT !.claims = @ + 1]
        ELSE IF w.kind = "agent" /\ q.auth /\ q.state \in AuthorOnly THEN [q EXCEPT !.claims = @ + 1]
        ELSE [q EXCEPT !.state = w.st,
                       !.auth = IF w.kind = "moderator" THEN w.sealed ELSE q.auth,
                       !.setter = w.kind]

RECURSIVE Run(_, _)
Run(q, ws) == IF ws = <<>> THEN q ELSE Run(Step(q, Head(ws)), Tail(ws))

VARIABLES q, n, last
vars == <<q, n, last>>

Init == q = Q0 /\ n = 0 /\ last = "none"
Next == /\ n < MaxWrites
        /\ \E w \in Writes : q' = Step(q, w) /\ last' = w.kind
        /\ n' = n + 1
Spec == Init /\ [][Next]_vars

TypeOK == q.state \in States /\ q.auth \in BOOLEAN /\ q.claims \in 0..MaxWrites

(* RF-GOV-01: an approved question was approved by the author, with a valid seal when signing is on *)
ApprovedByAuthor == q.state = "APPROVED" => q.setter = "moderator" /\ (Signing => q.auth)

(* RF-GOV-02: a rejected question was rejected by the author *)
RejectedByAuthor == q.state = "REJECTED" => q.setter = "moderator" /\ (Signing => q.auth)

(* RF-GOV-03: after a sealed approval, no agent write moves the question *)
ApprovalSticks == [][(q.state = "APPROVED" /\ q.auth /\ last' = "agent") => q'.state = q.state]_vars

(* RF-GOV-04: an agent write never moves a question into an author-only state *)
AgentNeverSetsAuthorOnly == [][(last' = "agent" /\ q'.state # q.state) => q'.state \notin AuthorOnly]_vars

(* RF-GOV-05: an agent write that is refused leaves the state and is counted as a claim *)
RefusalCounted == [][(last' = "agent" /\ q'.state = q.state /\ q'.setter = q.setter /\ q' # q)
                     => q'.claims = q.claims + 1]_vars

(* The table the conformance test replays on the real code: every thread of up to 3 writes *)
Threads3 == UNION {[1..k -> Writes] : k \in 0..3}
Table == {<<ws, Run(Q0, ws).state, Run(Q0, ws).auth, Run(Q0, ws).claims>> : ws \in Threads3}
=============================================================================
