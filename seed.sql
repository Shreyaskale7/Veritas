-- Demo data. User ids come out as: 1 admin, 2 Rao, 3 Iyer, 4 Hegde (HOD), 5-7 students.
INSERT INTO users (name, email, role) VALUES
 ('Exam Admin',      'admin@rvce.example',  'admin'),
 ('Dr. Rao',         'rao@rvce.example',    'faculty'),
 ('Prof. Iyer',      'iyer@rvce.example',   'faculty'),
 ('Dr. Hegde (HOD)', 'hegde@rvce.example',  'faculty'),
 ('Asha Nair',       'asha@rvce.example',   'student'),
 ('Bharat Shetty',   'bharat@rvce.example', 'student'),
 ('Chitra Menon',    'chitra@rvce.example', 'student');
INSERT INTO faculty (user_id, employee_id, department, can_approve) VALUES
 (2,'EMP-1001','CSE',false),(3,'EMP-1002','CSE',false),(4,'EMP-1000','CSE',true);
INSERT INTO students (user_id, usn, branch, semester) VALUES
 (5,'1RV24CD001','CSE (Data Science)',5),(6,'1RV24CD002','CSE (Data Science)',5),(7,'1RV24CD003','CSE (Data Science)',5);
INSERT INTO courses (course_code, title, credits, semester, faculty_id) VALUES
 ('CD252IA','Database Management Systems',4,5,2),
 ('CD251TA','Operating Systems',3,5,3),
 ('CD253TA','Software Engineering',3,5,4);
INSERT INTO assessments (course_id, type, max_marks, freeze_at)
 SELECT c.course_id, t.type, t.mx, now() + interval '30 days'
   FROM courses c, (VALUES ('CIE-1',50),('CIE-2',50),('SEE',100)) AS t(type, mx);
INSERT INTO marks (student_id, course_id, assessment_type)
 SELECT s.user_id, a.course_id, a.type FROM students s CROSS JOIN assessments a;
