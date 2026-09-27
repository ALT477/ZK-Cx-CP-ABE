"""
migrate_providers.py — converts Provider.hospital/.department/.speciality
(free text) into real FK references (hospital_id/department_id/speciality_id/
job_title_id) against the admin-managed taxonomy tables.

Must run AFTER the updated database.py/main.py have been deployed and the
app restarted at least once (so hospitals/departments/specialities/job_titles
exist as empty tables via create_tables()), but BEFORE any admin CRUD traffic
touches them.

Old "speciality" free text is actually job-title-shaped data ("Cardiologist",
"Intensivist") — it becomes JobTitle rows, not Speciality rows. Real
Speciality rows are derived from "department" via DEPT_TO_SPECIALITY below;
anything not in that mapping falls back to a Speciality row with the same
name as the department (nothing silently dropped — review these afterward
in the admin dashboard).
"""
import sqlite3
import sys

DB_PATH = "/opt/iotodchain/iotodchain.db"

DEPT_TO_SPECIALITY = {
    "Cardiology": "Cardiology",
    "ICU": "Intensive Care",
    "General": "General Medicine",
    "Diabetic": "Endocrinology",
}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()

    existing = cur.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    print(f"[migrate] {existing} existing provider rows")

    providers = cur.execute(
        "SELECT provider_id, full_name, role, hospital, department, speciality, "
        "city, photo_url, is_preseeded, created_at FROM providers"
    ).fetchall()

    # ── 1. Backfill hospitals ────────────────────────────────────────────
    hospital_ids = {}
    for row in providers:
        hospital, city = row[3], row[6]
        if hospital in hospital_ids:
            continue
        existing_row = cur.execute("SELECT id FROM hospitals WHERE name = ?", (hospital,)).fetchone()
        if existing_row:
            hospital_ids[hospital] = existing_row[0]
        else:
            cur.execute("INSERT INTO hospitals (name, city, is_active) VALUES (?, ?, 1)", (hospital, city))
            hospital_ids[hospital] = cur.lastrowid
    print(f"[migrate] hospitals: {len(hospital_ids)}")

    # ── 2. Backfill departments (scoped to hospital) ─────────────────────
    dept_ids = {}
    for row in providers:
        hospital, department = row[3], row[4]
        key = (hospital, department)
        if key in dept_ids:
            continue
        hid = hospital_ids[hospital]
        existing_row = cur.execute(
            "SELECT id FROM departments WHERE hospital_id = ? AND name = ?", (hid, department)
        ).fetchone()
        if existing_row:
            dept_ids[key] = existing_row[0]
        else:
            cur.execute(
                "INSERT INTO departments (hospital_id, name, is_active) VALUES (?, ?, 1)", (hid, department)
            )
            dept_ids[key] = cur.lastrowid
    print(f"[migrate] departments: {len(dept_ids)}")

    # ── 3. Backfill job_titles from the old "speciality" free text ───────
    job_title_ids = {}
    for row in providers:
        speciality = row[5]
        if not speciality or speciality in job_title_ids:
            continue
        existing_row = cur.execute("SELECT id FROM job_titles WHERE name = ?", (speciality,)).fetchone()
        if existing_row:
            job_title_ids[speciality] = existing_row[0]
        else:
            cur.execute("INSERT INTO job_titles (name, is_active) VALUES (?, 1)", (speciality,))
            job_title_ids[speciality] = cur.lastrowid
    print(f"[migrate] job_titles: {len(job_title_ids)}")

    # ── 4. Backfill specialities from department, via DEPT_TO_SPECIALITY ─
    speciality_ids = {}
    unmapped_departments = set()
    for row in providers:
        department = row[4]
        if department in speciality_ids:
            continue
        spec_name = DEPT_TO_SPECIALITY.get(department)
        if spec_name is None:
            spec_name = department
            unmapped_departments.add(department)
        existing_row = cur.execute("SELECT id FROM specialities WHERE name = ?", (spec_name,)).fetchone()
        if existing_row:
            speciality_ids[department] = existing_row[0]
        else:
            cur.execute("INSERT INTO specialities (name, is_active) VALUES (?, 1)", (spec_name,))
            speciality_ids[department] = cur.lastrowid
    print(f"[migrate] specialities: {len(speciality_ids)}")
    if unmapped_departments:
        print(f"[migrate] WARNING: no DEPT_TO_SPECIALITY mapping for {sorted(unmapped_departments)} "
              f"— fell back to a speciality named after the department; review in the admin dashboard")

    # ── 5. Rebuild providers with the new FK columns ─────────────────────
    cur.executescript("""
        CREATE TABLE providers_new (
            provider_id VARCHAR(64) PRIMARY KEY,
            full_name VARCHAR(128) NOT NULL,
            role VARCHAR(16) NOT NULL DEFAULT 'doctor',
            hospital VARCHAR(128) NOT NULL,
            department VARCHAR(128) NOT NULL,
            speciality VARCHAR(128),
            city VARCHAR(64) NOT NULL,
            photo_url VARCHAR(512),
            is_preseeded BOOLEAN,
            created_at DATETIME,
            hospital_id INTEGER REFERENCES hospitals(id),
            department_id INTEGER REFERENCES departments(id),
            speciality_id INTEGER REFERENCES specialities(id),
            job_title_id INTEGER REFERENCES job_titles(id)
        );
    """)

    for row in providers:
        provider_id, full_name, role, hospital, department, speciality, city, photo_url, is_preseeded, created_at = row
        hid = hospital_ids[hospital]
        did = dept_ids[(hospital, department)]
        sid = speciality_ids[department]
        jid = job_title_ids.get(speciality)
        cur.execute(
            "INSERT INTO providers_new (provider_id, full_name, role, hospital, department, speciality, "
            "city, photo_url, is_preseeded, created_at, hospital_id, department_id, speciality_id, job_title_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (provider_id, full_name, role, hospital, department, speciality, city, photo_url,
             is_preseeded, created_at, hid, did, sid, jid),
        )

    cur.execute("DROP TABLE providers")
    cur.execute("ALTER TABLE providers_new RENAME TO providers")

    conn.commit()

    final_count = cur.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    unresolved = cur.execute(
        "SELECT COUNT(*) FROM providers WHERE hospital_id IS NULL OR department_id IS NULL OR speciality_id IS NULL"
    ).fetchone()[0]
    print(f"[migrate] done — {final_count} providers migrated, {unresolved} with unresolved FKs (should be 0)")
    conn.close()


if __name__ == "__main__":
    main()
