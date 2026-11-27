# 2 Background

This chapter reviews the soil-water balance, low-cost sensing and existing scheduling methods, and ends on the two challenges the method addresses.

## 2.1 Soil-water balance

The water available to a crop is the difference between what enters the root zone and what leaves it. Rain and irrigation enter; evapotranspiration, drainage and run-off leave. The root zone behaves like a leaky bucket whose capacity is set by soil texture: sandy soils hold little water and drain quickly, clay soils hold more and release it slowly (Brennan, 2019).

Two thresholds organise most scheduling rules. *Field capacity* is the water content after free drainage has stopped; the *refill point* is the content below which the crop starts to suffer stress. Irrigation aims to keep the root zone between the two.

## 2.2 Low-cost soil-moisture sensing

Capacitive sensors estimate water content from the dielectric permittivity of the soil. They are cheap and robust, but their readings depend on salinity, temperature and the contact between the probe and the soil (Okafor et al., 2022). Field studies report three recurring failure modes: slow drift over a season, sudden offsets after the soil cracks around the probe, and gaps when the radio link fails (Tanaka & Moreau, 2023).

## 2.3 Scheduling methods

Scheduling methods fall into three families. Calendar methods irrigate on fixed days and need no data. Threshold methods irrigate when a sensor crosses the refill point. Model-based methods forecast the water balance and irrigate to keep it within bounds (Lindqvist, 2020).

Threshold methods are the most common in sensor-based systems because they are simple to explain. Their weakness is that a drifting sensor moves the threshold with it: a sensor that reads too wet delays irrigation until the crop is already stressed (Hartmann, 2018).

## 2.4 Learning the soil's response

A small body of work estimates the drainage curve of a plot from its own sensor readings, without laboratory calibration (Almeida & Costa, 2021). These methods fit an exponential decay to the readings that follow each irrigation event. They work well with clean data and have not been evaluated with the gaps and offsets that low-cost sensors produce in the field.

## 2.5 Summary and open challenges

The literature leaves two challenges open. First, no scheduler treats sensor quality as an input to the decision. Second, the online estimation of the drainage curve has only been tested on clean, laboratory-grade data. Chapter 3 addresses both.
