# confd_control

ConfD-backed database, BucketFS and storage administration from SQL: rewrites
`CONTROL DATABASE` / `CONTROL BUCKETFS` / `CONTROL STORAGE` commands into the
ConfD gateway calls that serve them — database info/backups, virtual restore,
license management, log/debug diagnostics, per-session log retrieval, BucketFS
service/bucket/file administration, and EXAStorage volume/node/remote-volume
inspection.

Deployed script: `PREPROC_RT.CONFD_CONTROL_V1`, function `confd_control`,
phase `EXPAND`. This is a composite module: the artifact installs **15
objects** — the entry script above, the 9 `PREPROC_RT` Python UDFs it
dispatches to, and the 5 `PREPROC.ADMIN_*_V1` Lua admin scripts those UDFs
call through — deployed by one `preproc module add`, retired and reclaimed as
one unit, and bound by a single DBA-scoped `EXPAND` rule on the entry script.

## Development home

[confd-via-sql](https://github.com/exasol-labs/confd-via-sql) is where this
module is developed: its `sql/` sources, specs, tests, docs, and issue
tracker all live there. This directory holds only what a `library-deployed`
module is published as — the generated artifact (`confd_control_v1.sql`),
its manifest (`module.toml`), this README, and `tests/` — never a copy of the
sources.

Built from confd-via-sql release 0.2.0 (commit `0b80ed542442462c032deeaa9d49c757e0c976e5`).

## Command domains

| Domain | Covers |
|---|---|
| `CONTROL DATABASE` | info, backups, virtual restore, license, log events, debug collect, session log |
| `CONTROL BUCKETFS` | services, buckets, file upload/list/show/delete |
| `CONTROL STORAGE` | volume/node inspection, remote volumes |

Every read command (`SHOW …`) rewrites to an inline-capable `EMITS` UDF call,
so it can be embedded in a larger statement (e.g.
`CREATE TABLE t AS SELECT * FROM (CONTROL STORAGE SHOW VOLUMES);`). Commands
that mutate state or need multi-step orchestration remain standalone
`EXECUTE SCRIPT` rewrites through a dedicated UDF + admin-script pair.

## Prerequisite

A `CONNECTION` object named `CONFD_CONNECTION` must exist before this module
is installed, pointing at the ConfD XML-RPC endpoint (port 20003 on the
first active node) with a user authorised to run ConfD jobs:

```sql
CREATE CONNECTION CONFD_CONNECTION
    TO 'https://<first-node-host>:20003'
    USER '<confd_user>' IDENTIFIED BY '<password>';
```

See confd-via-sql's own README and `docs/confd-admin.md` for how to create
that ConfD user and its required group memberships.

## Install

```
uv run preproc module add confd_control --registry /path/to/preprocessor-library
```

or, for an air-gapped database, bundle it for hand-carry:

```
uv run preproc module bundle confd_control --output confd_control.sql --registry /path/to/preprocessor-library
```

The suggested default scope is `FOR ROLE DBA`; the operator may deploy with a
different scope. Installing needs the `preproc module` CLI (`uv` + a DB
connection) — see `docs/operations.md` § Module management in the
`preprocessor-framework` repo for the CLI reference (including the
`--registry` flag and the air-gap `bundle` flow), and
`docs/module-authoring.md` there for the module contract.
