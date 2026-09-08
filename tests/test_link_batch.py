from __future__ import annotations

from pathlib import Path

from divapply.link_batch import canonicalize_job_url, parse_link_batch_file, parse_link_batch_text


def test_parse_link_batch_file_accepts_utf8_bom_and_skips_blanks_and_comments(tmp_path: Path) -> None:
    source = tmp_path / "jobs.txt"
    source.write_bytes(
        (
            "\ufeff# California jobs\r\n"
            "\r\n"
            "  https://jobs.example/roles/one  \r\n"
            "   # Local jobs\r\n"
            "https://jobs.example/roles/two\r\n"
        ).encode("utf-8")
    )

    result = parse_link_batch_file(source)

    assert result.source == source
    assert result.total_lines == 5
    assert result.ignored_lines == 3
    assert [(entry.line_number, entry.url) for entry in result.entries] == [
        (3, "https://jobs.example/roles/one"),
        (5, "https://jobs.example/roles/two"),
    ]
    assert result.invalid == ()
    assert result.duplicates == ()


def test_parser_preserves_inline_fragments_and_semantic_query_values() -> None:
    result = parse_link_batch_text(
        "\n".join(
            [
                "https://jobs.example/apply?job=100#step-one",
                "https://jobs.example/apply?job=101#step-one",
                "https://jobs.example/apply?job=100#step-two",
            ]
        )
    )

    assert [entry.url for entry in result.entries] == [
        "https://jobs.example/apply?job=100#step-one",
        "https://jobs.example/apply?job=101#step-one",
        "https://jobs.example/apply?job=100#step-two",
    ]
    assert [entry.canonical_url for entry in result.entries] == [
        "https://jobs.example/apply?job=100#step-one",
        "https://jobs.example/apply?job=101#step-one",
        "https://jobs.example/apply?job=100#step-two",
    ]


def test_parser_deduplicates_tracking_variants_in_first_seen_order() -> None:
    result = parse_link_batch_text(
        "\n".join(
            [
                "https://jobs.example:443/roles/one/?job=7&utm_source=board&gclid=abc#apply",
                "https://jobs.example/roles/two?job=8",
                "https://JOBS.EXAMPLE/roles/one?mc_cid=mail&job=7&utm_medium=email#apply",
            ]
        )
    )

    assert [entry.line_number for entry in result.entries] == [1, 2]
    assert result.entries[0].canonical_url == "https://jobs.example/roles/one?job=7#apply"
    assert len(result.duplicates) == 1
    assert result.duplicates[0].line_number == 3
    assert result.duplicates[0].duplicate_of_line == 1
    assert result.duplicates[0].canonical_url == result.entries[0].canonical_url


def test_parser_reports_invalid_external_urls_and_continues() -> None:
    result = parse_link_batch_text(
        "\n".join(
            [
                "ftp://jobs.example/one",
                "http://127.0.0.1/private",
                "https://user:password@jobs.example/private",
                "https://jobs.example/valid",
            ]
        )
    )

    assert [record.line_number for record in result.invalid] == [1, 2, 3]
    assert all(record.error for record in result.invalid)
    assert [(entry.line_number, entry.url) for entry in result.entries] == [
        (4, "https://jobs.example/valid")
    ]


def test_canonicalize_job_url_normalizes_only_identity_noise() -> None:
    canonical = canonicalize_job_url(
        "HTTPS://JOBS.EXAMPLE:443/posting/42/?b=2&utm_campaign=test&a=1&msclkid=tracking#questions"
    )

    assert canonical == "https://jobs.example/posting/42?a=1&b=2#questions"
