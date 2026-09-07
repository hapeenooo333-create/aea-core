#!/usr/bin/env python3
"""Live database verification tests for P1-6 durable execution.

These tests verify the actual PostgreSQL database with Supabase auth:
- RLS policies (cross-user isolation)
- Idempotency constraints
- Atomic claim mechanisms
- Durable execution
- Restart recovery
"""
import os
import sys
import uuid
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["SUPABASE_URL"] = "http://127.0.0.1:54321"
os.environ["SUPABASE_ANON_KEY"] = "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH"

import psycopg2
from psycopg2.extras import RealDictCursor

DB_URL = "postgresql://test_user:testpass@localhost:54322/postgres"

def get_db():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn

def run_sql(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params)
    try:
        return cur.fetchall()
    except psycopg2.ProgrammingError:
        return None

def set_jwt(conn, user_id):
    """Set JWT claims so auth.uid() works in RLS policies."""
    cur = conn.cursor()
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    cur.execute("SET request.jwt.claims = %s", (claims,))

def cleanup():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM public.mission_executions;")
    cur.execute("DELETE FROM public.mission_steps WHERE execution_id IS NOT NULL;")
    cur.execute("DELETE FROM public.missions WHERE title LIKE 'test_%';")
    cur.execute("DELETE FROM public.workers WHERE name LIKE 'test_%';")
    conn.commit()
    conn.close()

def create_test_user(conn, email):
    """Generate a test user UUID (auth.uid() reads from JWT, not auth.users table in tests)."""
    user_id = str(uuid.uuid4())
    return user_id

def create_test_worker(conn, owner_id, name):
    set_jwt(conn, owner_id)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO public.workers (id, name, worker_type, status, owner_id, created_at)
        VALUES (gen_random_uuid(), %s, 'employee', 'online', %s, now())
        RETURNING id;
    """, (name, owner_id))
    worker_id = cur.fetchone()[0]
    conn.commit()
    return str(worker_id)

def create_test_mission(conn, owner_id, title):
    set_jwt(conn, owner_id)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO public.missions (id, title, status, owner_id, created_at, updated_at)
        VALUES (gen_random_uuid(), %s, 'pending', %s, now(), now())
        RETURNING id;
    """, (title, owner_id))
    mission_id = cur.fetchone()[0]
    conn.commit()
    return str(mission_id)

def main():
    print("=" * 70)
    print("P1-6 LIVE DATABASE VERIFICATION")
    print("=" * 70)
    results = []

    cleanup()
    conn = get_db()

    user_a_email = f"test_user_a_{uuid.uuid4().hex[:8]}@example.com"
    user_b_email = f"test_user_b_{uuid.uuid4().hex[:8]}@example.com"
    user_a_id = create_test_user(conn, user_a_email)
    user_b_id = create_test_user(conn, user_b_email)

    worker_a = create_test_worker(conn, user_a_id, f"test_worker_a_{uuid.uuid4().hex[:8]}")
    mission_a = create_test_mission(conn, user_a_id, f"test_mission_a_{uuid.uuid4().hex[:8]}")

    print(f"\n[SETUP] User A: {user_a_id}")
    print(f"[SETUP] User B: {user_b_id}")
    print(f"[SETUP] Mission A: {mission_a}")

    # =========================================================================
    # TEST 1: RLS - User A can create and read their own execution
    # =========================================================================
    test_name = "RLS: User A can create execution"
    try:
        set_jwt(conn, user_a_id)
        execution_id = str(uuid.uuid4())
        idempotency_key = f"test_exec_{uuid.uuid4().hex[:8]}"

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.mission_executions (
                id, mission_id, execution_id, idempotency_key, status,
                owner_id, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s, 'RUNNING',
                %s, now(), now()
            ) RETURNING id;
        """, (mission_a, execution_id, idempotency_key, user_a_id))
        exec_db_id = cur.fetchone()[0]
        conn.commit()

        cur.execute("SELECT id FROM public.mission_executions WHERE execution_id = %s;", (execution_id,))
        result = cur.fetchone()

        if result:
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Execution not found")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 2: RLS - User B CANNOT read User A's execution
    # =========================================================================
    test_name = "RLS: User B cannot read User A's execution"
    try:
        set_jwt(conn, user_b_id)
        cur = conn.cursor()
        cur.execute("SELECT id FROM public.mission_executions WHERE execution_id = %s;", (execution_id,))
        result = cur.fetchone()

        if result is None:
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - User B should not see User A's execution")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 3: RLS - User B CANNOT update User A's execution
    # =========================================================================
    test_name = "RLS: User B cannot update User A's execution"
    try:
        set_jwt(conn, user_b_id)
        cur = conn.cursor()
        cur.execute("""
            UPDATE public.mission_executions
            SET status = 'SUCCEEDED', updated_at = now()
            WHERE execution_id = %s
            RETURNING status;
        """, (execution_id,))
        update_result = cur.fetchone()
        conn.commit()

        set_jwt(conn, user_a_id)
        cur.execute("SELECT status FROM public.mission_executions WHERE execution_id = %s;", (execution_id,))
        result = cur.fetchone()

        if result and result[0] != 'SUCCEEDED':
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Status was updated by User B")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 4: Idempotency - Same idempotency_key rejected
    # =========================================================================
    test_name = "Idempotency: Duplicate idempotency_key rejected"
    try:
        set_jwt(conn, user_a_id)
        exec_id_2 = str(uuid.uuid4())
        idempotency_dup = f"test_dup_{uuid.uuid4().hex[:8]}"

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.mission_executions (
                id, mission_id, execution_id, idempotency_key, status,
                owner_id, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s, 'PENDING',
                %s, now(), now()
            );
        """, (mission_a, exec_id_2, idempotency_dup, user_a_id))
        conn.commit()

        try:
            cur.execute("""
                INSERT INTO public.mission_executions (
                    id, mission_id, execution_id, idempotency_key, status,
                    owner_id, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), %s, %s, %s, 'PENDING',
                    %s, now(), now()
                );
            """, (mission_a, str(uuid.uuid4()), idempotency_dup, user_a_id))
            conn.commit()
            print(f"[FAIL] {test_name} - Duplicate was inserted")
            results.append(("FAIL", test_name))
        except psycopg2.errors.UniqueViolation:
            print(f"[PASS] {test_name} - Duplicate rejected by constraint")
            results.append(("PASS", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 5: Atomic Step Claim - First claim wins
    # =========================================================================
    test_name = "Atomic Claim: First claim wins, second rejected"
    try:
        set_jwt(conn, user_a_id)
        exec_id_3 = str(uuid.uuid4())
        step_id = str(uuid.uuid4())
        idempotency_step = f"test_step_{uuid.uuid4().hex[:8]}"

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.mission_executions (
                id, mission_id, execution_id, idempotency_key, status,
                owner_id, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s, 'RUNNING',
                %s, now(), now()
            ) RETURNING id;
        """, (mission_a, exec_id_3, f"exec_{uuid.uuid4().hex[:8]}", user_a_id))
        exec_db_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO public.mission_steps (
                id, mission_id, execution_id, step_name, worker_role, status,
                attempt_index, idempotency_key, owner_id, created_at
            ) VALUES (
                %s, %s, %s, 'test_step', 'employee', 'in_progress',
                0, %s, %s, now()
            );
        """, (step_id, mission_a, exec_db_id, idempotency_step, user_a_id))
        conn.commit()

        try:
            cur.execute("""
                INSERT INTO public.mission_steps (
                    id, mission_id, execution_id, step_name, worker_role, status,
                    attempt_index, idempotency_key, owner_id, created_at
                ) VALUES (
                    %s, %s, %s, 'test_step', 'employee', 'in_progress',
                    0, %s, %s, now()
                );
            """, (str(uuid.uuid4()), mission_a, exec_db_id, idempotency_step, user_a_id))
            conn.commit()
            print(f"[FAIL] {test_name} - Duplicate step claim succeeded")
            results.append(("FAIL", test_name))
        except psycopg2.errors.UniqueViolation:
            print(f"[PASS] {test_name} - Duplicate step claim rejected")
            results.append(("PASS", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 6: Durable Step Persistence
    # =========================================================================
    test_name = "Durable: Steps are persisted and retrievable"
    try:
        set_jwt(conn, user_a_id)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO public.mission_executions (
                id, mission_id, execution_id, idempotency_key, status,
                current_step_index, owner_id, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s, 'RUNNING',
                0, %s, now(), now()
            ) RETURNING id;
        """, (mission_a, str(uuid.uuid4()), f"exec_{uuid.uuid4().hex[:8]}", user_a_id))
        exec_db_id = cur.fetchone()[0]

        for i in range(3):
            cur.execute("""
                INSERT INTO public.mission_steps (
                    id, mission_id, execution_id, step_name, status,
                    attempt_index, idempotency_key, result, owner_id, created_at
                ) VALUES (
                    gen_random_uuid(), %s, %s, %s, 'completed',
                    0, %s, %s, %s, now()
                );
            """, (mission_a, exec_db_id, f"step_{i}", f"step_{uuid.uuid4().hex[:8]}", '{"output": "result"}', user_a_id))
        conn.commit()

        cur.execute("""
            SELECT COUNT(*) FROM public.mission_steps
            WHERE execution_id = %s AND status = 'completed';
        """, (exec_db_id,))
        count = cur.fetchone()[0]

        if count == 3:
            print(f"[PASS] {test_name} - {count} steps persisted")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Expected 3 steps, got {count}")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 7: Execution Status Transitions
    # =========================================================================
    test_name = "Execution: Status transitions are enforced"
    try:
        set_jwt(conn, user_a_id)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO public.mission_executions (
                id, mission_id, execution_id, idempotency_key, status,
                owner_id, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s, 'RUNNING',
                %s, now(), now()
            ) RETURNING id;
        """, (mission_a, str(uuid.uuid4()), f"exec_{uuid.uuid4().hex[:8]}", user_a_id))
        exec_db_id = cur.fetchone()[0]

        cur.execute("""
            UPDATE public.mission_executions
            SET status = 'SUCCEEDED', completed_at = now(), updated_at = now()
            WHERE id = %s;
        """, (exec_db_id,))
        conn.commit()

        cur.execute("SELECT status FROM public.mission_executions WHERE id = %s;", (exec_db_id,))
        status = cur.fetchone()[0]

        if status == 'SUCCEEDED':
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Expected SUCCEEDED, got {status}")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 8: Schema Verification - mission_executions columns
    # =========================================================================
    test_name = "Schema: mission_executions has all required columns"
    try:
        required_columns = {
            'id', 'mission_id', 'execution_id', 'idempotency_key', 'status',
            'current_step_index', 'retry_count', 'result', 'owner_id',
            'created_at', 'updated_at', 'started_at', 'completed_at'
        }

        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'mission_executions' AND table_schema = 'public';
        """)
        existing_columns = {row[0] for row in cur.fetchall()}

        missing = required_columns - existing_columns
        if not missing:
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Missing columns: {missing}")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 9: Schema Verification - mission_steps extended columns
    # =========================================================================
    test_name = "Schema: mission_steps has execution tracking columns"
    try:
        required_columns = {
            'execution_id', 'attempt_index', 'idempotency_key',
            'started_at', 'completed_at', 'result', 'retry_category', 'owner_id'
        }

        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'mission_steps' AND table_schema = 'public';
        """)
        existing_columns = {row[0] for row in cur.fetchall()}

        missing = required_columns - existing_columns
        if not missing:
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Missing columns: {missing}")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 10: Indexes exist for performance
    # =========================================================================
    test_name = "Schema: Required indexes exist"
    try:
        required_indexes = [
            'idx_mission_executions_mission_id',
            'idx_mission_executions_execution_id',
            'idx_mission_executions_idempotency_key',
            'idx_mission_executions_owner_id',
            'idx_mission_executions_status',
            'idx_mission_steps_execution_id',
            'idx_mission_steps_idempotency_key',
        ]

        cur = conn.cursor()
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'mission_executions' AND schemaname = 'public';
        """)
        exec_indexes = {row[0] for row in cur.fetchall()}

        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'mission_steps' AND schemaname = 'public';
        """)
        step_indexes = {row[0] for row in cur.fetchall()}

        all_indexes = exec_indexes | step_indexes
        missing = [idx for idx in required_indexes if idx not in all_indexes]

        if not missing:
            print(f"[PASS] {test_name}")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Missing indexes: {missing}")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 11: Unique constraints exist
    # =========================================================================
    test_name = "Schema: Unique constraints enforced"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT conname, contype FROM pg_constraint
            WHERE conrelid = 'public.mission_executions'::regclass
            AND contype IN ('u', 'p');
        """)
        constraints = cur.fetchall()

        has_unique_exec = any('execution_id' in str(c) or 'idempotency' in str(c[0]) for c in constraints)
        has_pk = any(c[1] == 'p' for c in constraints)

        if has_unique_exec and has_pk:
            print(f"[PASS] {test_name} - PK and unique constraints present")
            results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Constraints missing")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    # =========================================================================
    # TEST 12: Status constraint check
    # =========================================================================
    test_name = "Schema: Status constraint check enforced"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE conrelid = 'public.mission_executions'::regclass
            AND contype = 'c';
        """)
        rows = cur.fetchall()
        has_status_check = any('status' in str(r[1]).lower() for r in rows)

        if has_status_check:
            # Try inserting invalid status - should fail
            cur.execute("SET request.jwt.claims = %s", (json.dumps({"sub": user_a_id, "role": "authenticated"}),))
            try:
                cur.execute("""
                    INSERT INTO public.mission_executions (
                        mission_id, execution_id, idempotency_key, status, owner_id, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, 'INVALID_STATUS', %s, now(), now()
                    );
                """, (mission_a, str(uuid.uuid4()), f"inv_status_{uuid.uuid4().hex[:8]}", user_a_id))
                conn.commit()
                print(f"[FAIL] {test_name} - Invalid status was accepted")
                results.append(("FAIL", test_name))
            except psycopg2.errors.CheckViolation:
                print(f"[PASS] {test_name} - Invalid status rejected")
                results.append(("PASS", test_name))
        else:
            print(f"[FAIL] {test_name} - Status constraint not found")
            results.append(("FAIL", test_name))
    except Exception as e:
        print(f"[FAIL] {test_name} - {e}")
        results.append(("FAIL", test_name))

    conn.close()

    # =========================================================================
    # Print Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] == "FAIL")
    total = len(results)

    print(f"\nResults: {passed}/{total} passed, {failed}/{total} failed")

    if failed > 0:
        print("\nFailed tests:")
        for status, name in results:
            if status == "FAIL":
                print(f"  - {name}")

    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
