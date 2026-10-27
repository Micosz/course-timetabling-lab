# Verification record

Checked 2026-10-27. These are implementation checks, not final comparative research results.

- 12 automated Python tests pass on the actual adapted Fall CS input and small code fixtures.
- Four built-in methods pass the independent solution validator; evaluation accounting and lexicographic best-so-far traces checked.
- Repeated native runs with the same seed produce identical solutions/metrics when no time cap intervenes.
- Validator tests cover room, teacher, student conflicts; capacity; room type; availability; duplicate session-week; partial schedules; committed-background overlap; half-open intervals; SAME_TIME; repeated source constraint ID groups.
- Actual Safari browser runs with Pyodide 314.0.7: four methods × seed 42, budget 12. All four returned hard violations = 0 and budget accounting was correct (Greedy used 1; search methods used 12).
- Browser history survives page reload and reopens completed run data.
- Downloaded JSON contains four raw runs, the exact input dataset with matching SHA-256, and the five Python source files actually used by the worker. Downloaded CSV contains four result rows.
- Native CLI smoke: four methods × seed 42, budget 4; JSON and CSV written successfully.

Automated CI reruns the Python contract/regression suite. This record does not claim every browser/version or all custom Python programs have been tested. Imported bundles are not re-executed or independently authenticated merely by importing them.
