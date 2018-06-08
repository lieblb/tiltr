
-- patch "root" to root / odysseus
UPDATE usr_data SET passwd="$2y$10$/YK5.2Sn.QhxrTfrSuggJO3QkvpgO77aVisnbTL7tbtL2JlUg1sgK" WHERE login="root";
UPDATE usr_data SET last_password_change=NOW() WHERE login="root";
UPDATE usr_pref SET value="de" WHERE keyword="language";
