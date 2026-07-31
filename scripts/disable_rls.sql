-- Disable RLS for the workers and missions tables so inserts and reads work with the current anon client configuration.
ALTER TABLE workers DISABLE ROW LEVEL SECURITY;
ALTER TABLE missions DISABLE ROW LEVEL SECURITY;
