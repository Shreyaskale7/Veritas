-- Creates the first administrator on a production database (no seed users).
--   psql -d veritas -v name="Exam Admin" -v email=admin@college.edu -v password="a long passphrase" -f ops/create_admin.sql
-- (On a shared machine prefer PGOPTIONS or a here-file for the password: command lines are visible to other users.)
\set ON_ERROR_STOP on
INSERT INTO users (name, email, role) VALUES (:'name', :'email', 'admin') RETURNING user_id \gset
INSERT INTO app_credentials (user_id, password_hash) VALUES (:user_id, crypt(:'password', gen_salt('bf')));
\echo admin created with user_id :user_id
