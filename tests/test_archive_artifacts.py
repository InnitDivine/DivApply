from __future__ import annotations

from divapply.archive import artifact_siblings, delete_job_artifacts, is_safe_generated_path


def test_artifact_siblings_includes_resume_trace_files(tmp_path) -> None:
    resume = tmp_path / "Indeed_Support.txt"

    names = {path.name for path in artifact_siblings(resume)}

    assert names == {
        "Indeed_Support.txt",
        "Indeed_Support.pdf",
        "Indeed_Support.html",
        "Indeed_Support_JOB.txt",
        "Indeed_Support_REPORT.json",
    }


def test_delete_job_artifacts_only_deletes_under_generated_roots(tmp_path, monkeypatch) -> None:
    import divapply.config as config

    tailored_dir = tmp_path / "tailored"
    cover_dir = tmp_path / "cover"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)

    generated = tailored_dir / "Generated.txt"
    generated.write_text("delete", encoding="utf-8")
    outside = tmp_path / "resume.txt"
    outside.write_text("keep", encoding="utf-8")

    deleted = delete_job_artifacts({
        "tailored_resume_path": str(generated),
        "cover_letter_path": str(outside),
    })

    assert deleted == [generated]
    assert not generated.exists()
    assert outside.exists()
    assert not is_safe_generated_path(outside, [tailored_dir, cover_dir])


def test_delete_job_artifacts_rejects_parent_traversal_out_of_generated_roots(tmp_path, monkeypatch) -> None:
    import divapply.config as config

    tailored_dir = tmp_path / "tailored"
    cover_dir = tmp_path / "cover"
    outside_dir = tmp_path / "outside"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    outside_dir.mkdir()
    monkeypatch.setattr(config, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", cover_dir)

    outside = outside_dir / "Generated.txt"
    outside.write_text("keep", encoding="utf-8")
    traversal = tailored_dir / ".." / "outside" / "Generated.txt"

    deleted = delete_job_artifacts({"tailored_resume_path": str(traversal)})

    assert deleted == []
    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "keep"
