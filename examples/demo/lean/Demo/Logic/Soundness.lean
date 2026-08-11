import Demo.Logic.Rules

/-!
# Soundness

The syntactic proof system of paper:def:derivable and the theorem that it is
sound for the semantic triple: Theorem (soundness), which the paper labels
paper:thm:soundness.

That one item is cited twice in the two lines above, once by title and kind
and once by label.  Both are citations of the *same* paper item, and the
viewer should offer the reader two places in this module to stand, not two
different theorems.
-/

namespace Demo

/-- Derivability: paper:def:derivable.

The same five rules as the previous module, read as introduction rules of an
inductive family rather than as theorems.  Nothing here mentions `BigStep`;
that is what makes soundness a statement worth proving. -/
inductive Derivable : Assn → Cmd → Assn → Prop where
  | skip (P : Assn) : Derivable P Cmd.skip P
  | assign (P : Assn) (x : Var) (a : AExp) :
      Derivable (Assn.subst P x a) (Cmd.assign x a) P
  | seq {P Q R : Assn} {c₁ c₂ : Cmd} :
      Derivable P c₁ Q → Derivable Q c₂ R → Derivable P (Cmd.seq c₁ c₂) R
  | ite {P Q : Assn} {b : BExp} {c₁ c₂ : Cmd} :
      Derivable (fun s => P s ∧ b.eval s = true) c₁ Q →
      Derivable (fun s => P s ∧ b.eval s = false) c₂ Q →
      Derivable P (Cmd.ite b c₁ c₂) Q
  | whileDo {P : Assn} {b : BExp} {c : Cmd} :
      Derivable (fun s => P s ∧ b.eval s = true) c P →
      Derivable P (Cmd.whileDo b c) (fun s => P s ∧ b.eval s = false)

/-- paper:thm:soundness: everything derivable holds.

One case per rule, each discharged by the corresponding lemma of
`Demo/Logic/Rules`.  The whole content of the theorem is that the list of
rules in paper:def:derivable and the list of lemmas there are the same list. -/
theorem soundness {P Q : Assn} {c : Cmd} (d : Derivable P c Q) : Triple P c Q := by
  induction d with
  | skip P => exact skip_rule P
  | assign P x a => exact assign_rule P x a
  | seq _ _ ih₁ ih₂ => exact seq_rule ih₁ ih₂
  | ite _ _ ih₁ ih₂ => exact if_rule ih₁ ih₂
  | whileDo _ ih => exact while_rule ih

/-- paper:cor:derivable-holds — soundness with the triple unfolded, which is
the form a caller actually uses. -/
theorem derivable_holds {P Q : Assn} {c : Cmd} {s t : Store}
    (d : Derivable P c Q) (hs : P s) (h : BigStep c s t) : Q t :=
  soundness d s t hs h

end Demo
