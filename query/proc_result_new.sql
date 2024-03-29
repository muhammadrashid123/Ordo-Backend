/*MODIFIED 14 Daily Procedures: Grouped by Procedure Code. Like Internal*/
SET @FromDate = '{day_from}', @ToDate = '{day_to}'; -- Enter dates between '' in YYYY-MM-DD format
SET @Codes = '{proc_codes}'; -- Set the list of procedure codes to filter here
/*---DO NOT MODIFY BELOW THIS LINE---*/
/*Query code written/modified: 04/20/2020:SalinaK, 02/15/2023:AmyM*/
SELECT
def.ItemName AS 'Category',
pc.ProcCode AS 'Code',
pc.Descript AS 'Description',
COUNT(*) AS 'Quantity',
FORMAT(AVG(pl.ProcFee * (pl.UnitQty + pl.BaseUnits)),2) AS '$AvgFee_',
FORMAT(SUM(pl.ProcFee * (pl.UnitQty + pl.BaseUnits)),2) AS '$TotFee_'
FROM procedurelog pl
INNER JOIN procedurecode pc
ON pl.CodeNum = pc.CodeNum
AND IF(LENGTH(@Codes) = 0,TRUE,FIND_IN_SET(pc.ProcCode,@Codes)) -- Procedure code filter
INNER JOIN definition def
ON def.DefNum = pc.ProcCat
WHERE pl.ProcStatus = 2 -- Completed procedures
AND pl.ProcDate BETWEEN @FromDate AND @ToDate -- Date limitation
GROUP BY pc.ProcCode
ORDER BY def.ItemOrder, pc.ProcCode;
