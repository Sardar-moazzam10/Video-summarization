# Human Ground-Truth Concept Annotation Protocol & Sheet

## 1. Provenance & Guidelines
- **Purpose**: Establish human-verified reference concepts for holdout videos that were **never** used in VidFusion development, tuning, or prior project evaluation.
- **Reviewer Provenance**: Requires independent domain review (e.g. computer science instructors, domain specialists) with no knowledge of VidFusion selector internals or baseline outputs.
- **Independence Guarantee**: Reference concepts must be extracted purely from the uncurated full-length source transcripts, **never** from VidFusion or baseline candidate summaries.

## 2. Annotation Methodology
1. **Source Inspection**: The reviewer reads the complete transcript (or watches the lecture/video).
2. **Concept Unit Identification**: Identify 10–25 central thematic/technical concepts covered in the material.
3. **Tier Classification**:
   - `core` (Weight: 1.0): Essential conceptual pillars without which the subject cannot be understood.
   - `secondary` (Weight: 0.5): Illustrative examples, supporting technical details, or introductory context.
4. **Timestamp Grounding**: Identify all timestamp intervals $[t_{\text{start}}, t_{\text{end}}]$ where the speaker actively explains or demonstrates the concept.

---

## 3. Reference Annotation Sheet (Candidate Cases)

### Case 1: `QW_jlUn4gA8` (Kurzgesagt - "This Is What a Godlike Civilization Would Look Like")
- **Domain**: Astrophysics / Kardashev Scale
- **Candidate Concepts (Draft for Human Verification)**:
  1. *Kardashev Scale* (core) — classification of civilizations by energy consumption.
  2. *Dyson Sphere* (core) — megastructure capturing star energy output.
  3. *Matrioshka Brain* (core) — nested megastructure computers powered by star thermal gradients.
  4. *Stellar Engine / Shkadov Thruster* (secondary) — moving entire star systems across galactic space.
  5. *Iron Stars / Degenerate Era* (secondary) — long-term thermodynamic fate of matter.

### Case 2: `KkMDCCdjyW8` (Stanford CS106A - "Programming Methodology Lecture 1")
- **Domain**: Computer Science / Introductory Programming
- **Candidate Concepts (Draft for Human Verification)**:
  1. *Karel the Robot* (core) — foundational model for programmatic logic and execution.
  2. *Primitive Commands* (core) — move, turnLeft, pickBeeper, putBeeper instructions.
  3. *Function Definition / Decomposition* (core) — structuring instructions into named subroutines.
  4. *Syntactic vs Semantic Bugs* (secondary) — compiler-caught errors versus runtime behavioral errors.
  5. *Course Administration & Honor Code* (secondary) — logistics, assignment policy, academic integrity.

### Case 3: `sRuyBNxCkGQ` (Stanford CS149 - "Parallel Computing Lecture 15")
- **Domain**: Computer Science / Systems & Compilers
- **Candidate Concepts (Draft for Human Verification)**:
  1. *Domain-Specific Languages (DSLs)* (core) — expressiveness vs compiler optimization opportunities.
  2. *Separation of Algorithm from Schedule* (core) — Halide architecture decoupling compute from loop order.
  3. *Tiling and Locality* (core) — cache optimization via iteration space partitioning.
  4. *Vectorization and SIMD* (secondary) — hardware vector units and compiler auto-vectorization limits.
  5. *Fusion and Storage Reductions* (secondary) — producer-consumer pipelining to avoid round-trips to DRAM.

---

## 4. Current Status
> **Status: Semantic efficacy validation pending human annotation.**
> Because formal human panel scoring has not yet been executed on these unseen materials, VidFusion's semantic concept recall, precision, and F1 claims on holdout data remain explicitly pending. All current holdout comparisons are strictly grounded in structural, duration, temporal coverage, redundancy, and ordering metrics.
