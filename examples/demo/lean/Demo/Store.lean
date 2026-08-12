/-!
# Stores and their updates

The bottom of the development: nothing imports less than this module, and
everything else imports it.  Its content is the companion note's, not the
paper's — the paper takes stores for granted and the note is where they are
actually pinned down.

Both documents introduce the same object under the same label, so the two
citations here are the demo's disambiguation case: `paper:def:state` is the
paper's, `note, def:state` is the note's, and only the marker in front of each
tells them apart.  See `markers` in `interproof.toml`.

Alphabetically this module is fourth of five; in import order it is first.
That is the whole argument for reading the file index in import order.
-/

namespace Demo

/-- Program variables.  A `String` rather than an abstract type: the demo has
no reason to be polymorphic, and `DecidableEq String` comes for free. -/
abbrev Var := String

/-- A store: a total map from variables to natural numbers.

Totality is the paper's convenience and the note's (`paper:def:state`,
`note, def:state`): with no partial stores there is no uninitialised-variable
case anywhere below. -/
abbrev Store := Var → Nat

/-- `Store.update s x n` is the note's `σ[x ↦ n]` (note, def:update): the
store that answers `n` at `x` and agrees with `s` everywhere else.  Every
state change in the language is built from this one operation. -/
def Store.update (s : Store) (x : Var) (n : Nat) : Store :=
  fun y => if y = x then n else s y

/-- Reading back what was just written — the first branch of the note's
update, note, def:update:eq. -/
@[simp]
theorem update_same (s : Store) (x : Var) (n : Nat) :
    Store.update s x n x = n := by
  simp [Store.update]

/-- Reading past a write to another variable — the other branch,
note, def:update:ne. -/
theorem update_ne (s : Store) {x y : Var} (n : Nat) (h : y ≠ x) :
    Store.update s x n y = s y := by
  simp [Store.update, h]

/-! ## Rearranging updates

This section comment sits immediately after a declaration, and it closes the
same way a docstring closes.  Mistaking it for one sends the search for the
opening delimiter back past `update_ne` and into the previous declaration's
own docstring, and the citation band then starts a whole declaration early.
The parser asks the comment spans rather than the line text; this block is the
regression case for that.
-/

/-- The second write wins: `note, lem:update-shadow`.

The `@[simp]` below is deliberate.  An attribute between a docstring and its
declaration must not detach the two. -/
@[simp]
theorem update_shadow (s : Store) (x : Var) (m n : Nat) :
    Store.update (Store.update s x m) x n = Store.update s x n := by
  funext y
  by_cases h : y = x
  · simp [Store.update, h]
  · simp [Store.update, h]

/-- Writes to distinct variables commute: `note, lem:update-comm`. -/
theorem update_comm (s : Store) {x y : Var} (h : x ≠ y) (m n : Nat) :
    Store.update (Store.update s x m) y n
      = Store.update (Store.update s y n) x m := by
  -- Extensionality in `z`: note, lem:update-comm:ext.
  funext z
  -- The case split on `z = x` and on `z = y`: note, lem:update-comm:split.
  by_cases hzx : z = x
  · subst hzx
    -- `x ≠ y` rules out the disagreeing branch: note, lem:update-comm:ne.
    simp [Store.update, h]
  · by_cases hzy : z = y
    · subst hzy
      simp [Store.update, hzx]
    · simp [Store.update, hzx, hzy]

/-! ## Frames -/

/-- Agreement on a frame, written `∼_W`: def:frame, and to the point the
agreement clause of it, def:frame:agree.

Both citations name a label and nothing else — no document marker appears
anywhere before either.  They resolve because only one of the two documents
holds that label, which is the usual case and the reason most citations need
no ceremony. -/
def AgreeOn (W : List Var) (s t : Store) : Prop :=
  ∀ x ∈ W, s x = t x

/-- Writing outside a frame leaves the frame alone: `note, lem:frame-update`. -/
theorem agreeOn_update_of_not_mem {W : List Var} {x : Var} (s : Store) (n : Nat)
    (hx : x ∉ W) : AgreeOn W s (Store.update s x n) := by
  intro y hy
  have hne : y ≠ x := fun h => hx (h ▸ hy)
  simp [Store.update, hne]

end Demo
