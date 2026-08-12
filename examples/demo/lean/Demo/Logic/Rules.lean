import Demo.Semantics

/-!
# Hoare rules

The proof rules of paper:sec:hoare, each one stated directly on the semantic
triple of paper:def:triple rather than on a derivability judgement.  The
judgement itself is the next module up; keeping the two apart is what makes
soundness a five-line induction there instead of a hundred-line one here.

This module sits in a subdirectory.  The parser keys a module by its path
under the formal root, so this one is `Demo/Logic/Rules`, and a second
`Rules.lean` elsewhere in the tree would not collide with it.
-/

namespace Demo

/-- An assertion — a predicate on stores: paper:def:assn.  Semantic, so no
assertion language has to be fixed. -/
abbrev Assn := Store → Prop

/-- The partial-correctness triple of paper:def:triple.

Partial: a command with no big-step derivation from `s` satisfies every
triple, which is exactly what makes the loop rule provable without a
termination argument. -/
def Triple (P : Assn) (c : Cmd) (Q : Assn) : Prop :=
  ∀ s t : Store, P s → BigStep c s t → Q t

/-- Substitution into an assertion: paper:def:subst.  Composition with an
update (cf. note, def:update), because assertions here are semantic — the
`cf.` says this declaration is not the update, it only rests on it. -/
def Assn.subst (P : Assn) (x : Var) (a : AExp) : Assn :=
  fun s => P (Store.update s x (a.eval s))

/-- paper:lem:hoare-skip. -/
theorem skip_rule (P : Assn) : Triple P Cmd.skip P := by
  intro s t hP h
  cases h
  exact hP

/-- paper:lem:hoare-assign.  The backwards form: the precondition is computed
from the postcondition, which is what makes it usable. -/
theorem assign_rule (P : Assn) (x : Var) (a : AExp) :
    Triple (Assn.subst P x a) (Cmd.assign x a) P := by
  intro s t hP h
  cases h
  exact hP

/-! ## Composition, branching and loops

A second section comment directly after a declaration.  The three rules below
are the ones with premises, and they are the reason the module needs a
`variable` block at all.
-/

section Structural

variable {P Q R : Assn} {b : BExp} {c c₁ c₂ : Cmd}

/-- paper:lem:hoare-seq. -/
theorem seq_rule (h₁ : Triple P c₁ Q) (h₂ : Triple Q c₂ R) :
    Triple P (Cmd.seq c₁ c₂) R := by
  intro s u hP h
  cases h with
  | seq hc₁ hc₂ => exact h₂ _ _ (h₁ _ _ hP hc₁) hc₂

/-- paper:lem:hoare-if.  Each branch carries the test's value as an extra
conjunct, which is precisely the premise the corresponding semantic rule
supplies. -/
theorem if_rule
    (h₁ : Triple (fun s => P s ∧ b.eval s = true) c₁ Q)
    (h₂ : Triple (fun s => P s ∧ b.eval s = false) c₂ Q) :
    Triple P (Cmd.ite b c₁ c₂) Q := by
  intro s t hP h
  cases h with
  | iteTrue hb hc => exact h₁ _ _ ⟨hP, hb⟩ hc
  | iteFalse hb hc => exact h₂ _ _ ⟨hP, hb⟩ hc

/-- paper:lem:hoare-while.

Left open.  The proof is an induction on the big-step derivation with the
store generalised, and the demo keeps exactly one `sorry` so that the reader
can see what an incomplete declaration looks like in the viewer. -/
theorem while_rule (h : Triple (fun s => P s ∧ b.eval s = true) c P) :
    Triple P (Cmd.whileDo b c) (fun s => P s ∧ b.eval s = false) := by
  -- Induction on the big-step derivation, generalising the store.
  sorry

end Structural

/-! ## What is missing

The paper's proof system also has a rule of consequence, and this module does
not.  It is left out on purpose: an example in which every statement of the
paper has a counterpart shows nothing about a tool whose subject is the gap
between the two sides.

The label paper:def:triple is cited here for the second time in this file, a
hundred lines below the module header that cites it first.  Those are two
places a reader might want to be taken to, not one region spanning everything
between them, and the lines in between cite nothing at all.
-/

end Demo
