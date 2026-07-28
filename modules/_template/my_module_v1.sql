--/
CREATE OR REPLACE LUA SCRIPT PREPROC_RT.MY_MODULE_V1 AS
-- =============================================================================
-- MY_MODULE_V1  (PREPROC_RT.MY_MODULE_V1)
-- =============================================================================
-- This is a placeholder TRANSLATE-phase module for the modules/_template/
-- skeleton. Copy this whole modules/_template/ directory to
-- modules/<your-module-name>/ and replace this body with your own logic.
--
-- See docs/module-authoring.md in the preprocessor-framework repo for the
-- full function contract per phase (TRANSLATE/EXPAND/REWRITE), the
-- fail-open/fail-closed rules, and the "no defensive pcall" rule.
-- =============================================================================

-- luacheck: globals my_module

-- my_module(sqltext) -> sqltext, unchanged.
-- A TRANSLATE-phase module MUST return a string on every path. This
-- placeholder returns the input unchanged; replace the body with your own
-- transform.
function my_module(sqltext)
    return sqltext
end
/
