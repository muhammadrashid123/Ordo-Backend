/* Manual query based on 61. Please use this query at your own risk. */
/*Query code written/modified 03/07/2023*/

SET @Codes ='{codes}'; /*Enter exact procedure codes here, separated by a | symbol. Must not end in a | . Will search all if left blank.*/
SET @StartDate='{day_from}' , @EndDate='{day_to}'; /*Enter dates here in YYYY-MM-DD format*/

/*---DO NOT MODIFY BELOW THIS LINE---*/

SET @Codes=(CASE WHEN @Codes='' THEN '^' ELSE CONCAT('^',REPLACE(@Codes,'|','$|^'),'$') END);

SELECT (pc.ProcCode) AS 'ProcCode', COUNT(pc.ProcCode) as Count
FROM patient
INNER JOIN procedurelog  pl
	ON patient.PatNum=pl.PatNum
INNER JOIN procedurecode pc
	ON pl.CodeNum= pc.CodeNum
INNER JOIN appointment ap
	ON pl.AptNum=ap.AptNum
	AND ap.AptStatus IN (1,4) /*Scheduled or ASAP*/
	AND ProcCode REGEXP @Codes
	AND DATE(ap.AptDateTime) BETWEEN @StartDate AND @EndDate
GROUP by pc.ProcCode
ORDER BY pc.ProcCode ASC;
