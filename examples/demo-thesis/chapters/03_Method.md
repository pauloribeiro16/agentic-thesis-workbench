# 3 Method

This chapter presents the scheduling method in three stages and states what each stage takes in and gives out.

## 3.1 Overview

The method has three stages that run every morning on each plot. A quality stage scores every sensor node from its recent readings. An estimation stage updates the plot's drainage curve from the readings the quality stage trusts. A decision stage turns the estimated water content and the weather forecast into an irrigation volume, or into no irrigation at all.

## 3.2 Sensor-quality model

Each node receives a quality score between zero and one. The score combines three indicators: the share of expected readings that arrived in the last 48 hours, the size of any step change that is not explained by rain or irrigation, and the slope of the residual between the node and the median of its neighbours over the last fourteen days (Tanaka & Moreau, 2023). A node whose score falls below 0.5 is excluded from estimation until it recovers.

## 3.3 Online estimation of the drainage curve

After each irrigation event the readings of trusted nodes are fitted to an exponential decay towards field capacity. The fitted rate is blended with the previous estimate, so that a single noisy event cannot move the curve far (Almeida & Costa, 2021). When fewer than two nodes are trusted, the previous estimate is kept and the decision stage widens its safety margin.

## 3.4 Irrigation decision

The decision stage forecasts the root-zone water content for the next three days from the drainage curve and the reference evapotranspiration of the forecast. If the forecast crosses the refill point before the next scheduled check, it irrigates the volume that brings the root zone back to field capacity, minus the rain expected in the next 24 hours. The volume is rounded to whole minutes of pump time, because that is how farmers operate the pump.

## 3.5 Implementation

The method runs on a single-board computer at the farm and sends the decision to the farmer's phone as a short text message. All computation is local, so the schedule is still produced when the internet connection is down.
