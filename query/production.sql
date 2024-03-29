/*Modified query based on 1069 by Alan 2023-02-23. Please use this query at your own risk.*/

/*Set date range and provider at top*/

/*Query code written/modified:  02/26/2019 AlexG*/
SET
  @FromDate = '{day_from}',
  @ToDate  = '{day_to}';
SET
  @ProvAbbr = '%%';
/*Set the abbreviation of the provider here*/
SET
  @WriteoffByDateOfService = '';
/*Set to Yes to have writeoffs by date of service. Blank to run by payment date.*/
SELECT
  SUM($NetProd_) AS Adjusted_Production,
  SUM($TotalIncome_) AS 'Collections'
FROM
  (
    SELECT
      Trans.TransDate AS 'Date',
      DATE_FORMAT(Trans.TransDate, '%W') AS 'WeekDay',
      SUM(
        CASE WHEN Trans.TranType = 'Prod' THEN Trans.TranAmount ELSE 0 END
      ) AS $Production_,
      SUM(
        CASE WHEN Trans.TranType = 'Sched' THEN Trans.TranAmount ELSE 0 END
      ) AS $Sched_,
      SUM(
        CASE WHEN Trans.TranType = 'Adj' THEN Trans.TranAmount ELSE 0 END
      ) AS $Adjustment_,
      SUM(
        CASE WHEN Trans.TranType = 'Writeoff' THEN Trans.Writeoff ELSE 0 END
      ) AS $Writeoff_,
      SUM(
        CASE WHEN Trans.TranType IN('Prod', 'Adj', 'Sched') THEN Trans.TranAmount WHEN Trans.TranType IN('Writeoff') THEN Trans.Writeoff ELSE 0 END
      ) AS $NetProd_,
      SUM(
        CASE WHEN Trans.TranType IN('InsPayEst', 'InsPayEst2') THEN - Trans.TranAmount ELSE 0 END
      ) AS $EstInsIncome_,
      SUM(
        CASE WHEN Trans.TranType IN(
          'Prod', 'Adj', 'Sched', 'InsPayEst',
          'InsPayEst2'
        ) THEN Trans.TranAmount ELSE 0 END
      ) AS $EstPatIncome_,
      SUM(
        CASE WHEN Trans.TranType = 'PatPay' THEN Trans.TranAmount ELSE 0 END
      ) AS $PatIncome_,
      SUM(
        CASE WHEN Trans.TranType IN('InsPay') THEN Trans.TranAmount ELSE 0 END
      ) AS $InsIncome_,
      SUM(
        CASE WHEN Trans.TranType IN('PatPay', 'InsPay') THEN Trans.TranAmount ELSE 0 END
      ) AS $TotalIncome_
    FROM
      (

        /*Prod*/
        SELECT
          'Prod' AS TranType,
          pl.ProcDate AS TransDate,
          pl.ProvNum,
          pl.ProcFee *(pl.UnitQty + pl.BaseUnits)- IFNULL(
            SUM(cp.WriteOff),
            0
          ) AS TranAmount,
          0 AS Writeoff
        FROM
          procedurelog pl
          LEFT JOIN claimproc cp ON pl.ProcNum = cp.ProcNum
          AND cp.Status = '7'
        WHERE
          pl.ProcStatus = 2
          AND pl.ProcDate BETWEEN @FromDate
          AND @ToDate
        GROUP BY
          pl.ProcNum
        UNION ALL

          /*Sched*/
        SELECT
          'Sched' AS TranType,
          DATE(ap.AptDateTime) AS TransDate,
          ap.ProvNum,
          COALESCE(
            SUM(
              pl.ProcFee *(pl.UnitQty + pl.BaseUnits)
            ),
            0
          ) AS TranAmount,
          0 AS Writeoff
        FROM
          appointment ap
          LEFT JOIN procedurelog pl ON ap.AptNum = pl.AptNum
        WHERE
          ap.AptStatus IN (1, 4)
          /*Scheduled,ASAP*/
          AND DATE(ap.AptDateTime) BETWEEN @FromDate
          AND @ToDate
        GROUP BY
          ap.AptNum
        UNION ALL

          /*Adj*/
        SELECT
          'Adj' AS TranType,
          a.AdjDate AS TransDate,
          a.ProvNum,
          a.AdjAmt AS TranAmount,
          0 AS Writeoff
        FROM
          adjustment a
        WHERE
          a.AdjDate BETWEEN @FromDate
          AND @ToDate
        UNION ALL

          /*PatInc*/
        SELECT
          'PatPay' AS TranType,
          ps.DatePay AS TransDate,
          ps.ProvNum,
          ps.SplitAmt AS TranAmount,
          0 AS Writeoff
        FROM
          paysplit ps
        WHERE
          ps.IsDiscount = 0
          AND ps.DatePay BETWEEN @FromDate
          AND @ToDate
        UNION ALL

          /*InsIncome*/
        SELECT
          'InsPay' AS TranType,
          cp.DateCP AS TransDate,
          cp.ProvNum,
          cp.InsPayAmt AS TranAmount,
          0 AS Writeoff
        FROM
          claimproc cp
          INNER JOIN claimpayment cpm ON cp.ClaimPaymentNum = cpm.ClaimPaymentNum
          INNER JOIN insplan ip ON cp.PlanNum = ip.PlanNum
          INNER JOIN carrier car ON car.CarrierNum = ip.CarrierNum
        WHERE
          cp.DateCP BETWEEN @FromDate
          AND @ToDate
          AND cp.Status IN(1, 4)
        UNION ALL

          /*Writeoff*/
        SELECT
          'Writeoff' AS TranType,
          (
            CASE WHEN @WriteoffByDateOfService = 'YES' THEN cp.ProcDate ELSE cp.DateCP END
          ) AS TransDate,
          cp.ProvNum,
          0 AS TranAmount,
          - cp.WriteOff AS Writeoff
        FROM
          claimproc cp
        WHERE
          (
            CASE WHEN @WriteoffByDateOfService = 'YES' THEN cp.ProcDate ELSE cp.DateCP END
          ) BETWEEN @FromDate
          AND @ToDate
          AND IF(
            @WriteoffByDateOfService = 'YES',
            cp.Status IN(0, 1, 4),
            cp.Status IN(1, 4)
          )
        UNION ALL

          /*EstInsIncome*/
        SELECT
          'InsPayEst' AS TranType,
          cp.ProcDate AS TransDate,
          cp.ProvNum,
          -(
            (
              COALESCE(
                (
                  CASE WHEN cp.Status = 1
                  OR cp.Status = 4 THEN(cp.WriteOff) ELSE(
                    CASE WHEN cp.WriteOffEstOverride =-1 THEN (
                      CASE WHEN cp.WriteOffEst =-1 THEN 0 ELSE cp.WriteOffEst END
                    ) ELSE (cp.WriteOffEstOverride) END
                  ) END
                ),
                0
              )
            ) +(
              COALESCE(
                (
                  CASE WHEN cp.Status = 1
                  OR cp.Status = 4 THEN(cp.InsPayAmt) ELSE (
                    CASE WHEN cp.InsEstTotalOverride =-1 THEN(cp.InsEstTotal) ELSE (cp.InsEstTotalOverride) END
                  ) END
                ),
                0
              )
            )
          ) AS TranAmount,
          0 AS Writeoff
        FROM
          claimproc cp
          INNER JOIN insplan ip ON cp.PlanNum = ip.PlanNum
          INNER JOIN carrier car ON car.CarrierNum = ip.CarrierNum
          INNER JOIN procedurelog pl ON pl.ProcNum = cp.ProcNum
          AND pl.ProcStatus = 2
        WHERE
          cp.ProcDate BETWEEN @FromDate
          AND @ToDate
          AND cp.Status IN(0, 1, 4, 6)
        UNION ALL
        SELECT
          'InsPayEst2' AS TranType,
          DATE(appt.AptDateTime) AS TransDate,
          cp.ProvNum,
          -(
            (
              COALESCE(
                (
                  CASE WHEN cp.WriteOffEstOverride =-1 THEN (
                    CASE WHEN cp.WriteOffEst =-1 THEN 0 ELSE cp.WriteOffEst END
                  ) ELSE (cp.WriteOffEstOverride) END
                ),
                0
              )
            ) +(
              COALESCE(
                (
                  CASE WHEN cp.Status = 0 THEN(cp.InsPayEst) WHEN cp.Status = 6 THEN(
                    CASE WHEN cp.InsEstTotalOverride =-1 THEN(cp.InsEstTotal) ELSE (cp.InsEstTotalOverride) END
                  ) END
                ),
                0
              )
            )
          ) AS TranAmount,
          0 AS Writeoff
        FROM
          claimproc cp
          INNER JOIN procedurelog pl ON pl.ProcNum = cp.ProcNum
          AND pl.ProcStatus = 1
          INNER JOIN appointment appt ON appt.AptNum = pl.AptNum
          AND appt.AptStatus IN (1, 4)
          AND DATE(appt.AptDateTime) BETWEEN @FromDate
          AND @ToDate
          INNER JOIN insplan ip ON cp.PlanNum = ip.PlanNum
          INNER JOIN carrier car ON car.CarrierNum = ip.CarrierNum
          AND cp.Status IN(0, 6)
      ) Trans
      INNER JOIN provider pv ON pv.ProvNum = Trans.ProvNum
      AND pv.Abbr LIKE @ProvAbbr
    GROUP BY
      Trans.TransDate
    ORDER BY
      Trans.TransDate
  ) AS prod_collections;
