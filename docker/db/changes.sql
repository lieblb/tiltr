
-- patch "root" to root / odysseus
UPDATE usr_data SET passwd="$2y$10$/YK5.2Sn.QhxrTfrSuggJO3QkvpgO77aVisnbTL7tbtL2JlUg1sgK" WHERE login="root";
UPDATE usr_data SET last_password_change=NOW() WHERE login="root";
UPDATE usr_pref SET value="de" WHERE keyword="language";

-- patch settings
UPDATE settings SET value=0 WHERE module="common" AND keyword="ps_password_change_on_first_login_enabled";

UPDATE settings SET value='13,5,10,14,12,7,15,8,6,17,3,2,9,1,4,18' WHERE module="assessment" AND keyword="assessment_scoring_adjustment";
UPDATE settings SET value='1' WHERE module="assessment" AND keyword="assessment_adjustments_enabled";
