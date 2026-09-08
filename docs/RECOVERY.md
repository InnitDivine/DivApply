# Recovery and a clean Windows installation

Keep two separate recovery sets. GitHub stores source code and tests, **not** your
profile, passwords, API keys, database, transcripts, or generated applications.
A source push alone does not make a computer safe to reset.

## Before resetting the computer

1. Stop active DivApply runs and finish or save browser applications.
2. Save the tested source revision to GitHub. Preserve history; do not use a
   force-push or a release tag just to back up source. Release tags trigger
   publishing workflows.
3. Run `divapply system backup --help`, then create a private backup with outputs.
   Credentials are excluded unless explicitly requested. A backup containing
   credentials is sensitive and is **not encrypted** by DivApply.
4. Put the private backup on an approved external drive or secure backup service.
   Prefer encryption when including secrets. Verify the copied archive's SHA-256
   against the original with PowerShell `Get-FileHash -Algorithm SHA256`.
5. Open and test the archive, restore it into a separate empty folder, and verify
   the database, profile, coursework, and documents. Keep the original untouched.
6. Separately save original transcripts, certificates, edited documents outside
   DivApply, and unrelated personal files. DivApply's backup does not cover the
   entire PC, browser sessions, installed applications, or all Downloads files.

Do not reset until the off-PC copy and recovery test are verified.

## Reinstall the application

Install Git and a standalone Python 3.12 interpreter, then clone the repository
and check out the tested recovery revision. Do not copy an old `.venv`: it can
contain absolute paths to a Python installation that no longer exists.

From the cloned repository in Command Prompt:

```bat
install.cmd
```

The installer creates the environment, installs the supported JobSpy runtime,
downloads Playwright Chromium, and registers the per-user `divapply` command.
Open a **new** terminal afterward:

```bat
divapply
divapply system check
```

If the command is missing, rerun `install.cmd` from the checkout rather than
adding several competing launchers. Node and the configured application agent
must also be installed and authenticated for assisted browser applications.
Browser accounts will need sign-in again; restoring a data ZIP does not restore
browser sessions.

## Restore private data without overwriting it

Use only a backup you created and verified. Extract it to a new empty folder,
not over a live installation. The files should be directly inside the restored
folder (for example, `profile.json`, `searches.yaml`, and the database), not under
an extra ZIP-name directory.

Point one new Command Prompt session at that folder using an absolute path:

```bat
set "DIVAPPLY_DIR=C:\path\to\restored-private-data"
divapply system check
divapply status
```

This setting applies only to that terminal. Confirm profile and school status,
coursework counts, job counts, and document availability before adopting the
restored folder permanently. Historical document paths may refer to the old
Windows username; verify those paths and use the application's repair workflow
before generating duplicates. Existing degree completion and certification facts
must remain separate from any hypothetical scoring assumptions.

Run a small, explicitly approved job preparation test before a large run. Offline
tests do not prove provider access, current employer-page extraction, browser
sign-in, or application submission works. Never submit an application merely to
test recovery.

## Known dependency exception

JobSpy 1.1.82 declares an old markdownify upper bound. DivApply intentionally
installs a newer markdownify because of the upstream security issue documented
in `PUBLISHING.md`. Consequently, generic `pip check` reports that conflict.
Use `divapply system check` and `python -m divapply.jobspy_runtime` to validate
the supported runtime; do not downgrade markdownify just to silence pip.
