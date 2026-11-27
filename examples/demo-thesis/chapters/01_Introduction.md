# 1 Introduction

This chapter states the problem, the research question and the objectives, and outlines the rest of the thesis.

## 1.1 Context

Smallholder farms produce a large share of the food consumed in low- and middle-income regions, yet most of them still schedule irrigation by habit rather than by measurement (Almeida & Costa, 2021). Water is applied on fixed days, often in the hottest hours, and the amount depends on how long the pump runs rather than on what the soil needs. Over-irrigation wastes water and energy and leaches nutrients below the root zone; under-irrigation reduces yield at the stages where the crop is most sensitive (Brennan, 2019).

Low-cost capacitive soil-moisture sensors have changed what a small farm can measure. A sensor node that reports volumetric water content every fifteen minutes now costs less than a day of hired labour (Okafor et al., 2022). The measurement, however, is not the decision. A farmer still has to turn a stream of noisy readings into a simple answer: whether to irrigate today, and for how long.

## 1.2 Problem statement

Existing scheduling methods assume either a calibrated sensor network or a full agronomic model of the crop, the soil and the weather (Lindqvist, 2020). Neither assumption holds on a smallholder farm. Sensors drift, are installed at inconsistent depths and lose connectivity for days at a time. Agronomic models need parameters that nobody on the farm can supply.

The gap this thesis addresses is therefore not the lack of sensors or the lack of models, but the lack of a scheduling method that stays useful when the data are incomplete and the parameters are unknown.

## 1.3 Research question and objectives

The research question is: *how can irrigation be scheduled from low-cost soil-moisture sensors so that water use falls without a loss of yield, when sensor data are incomplete and soil parameters are not known in advance?*

Three objectives follow from it:

1. to characterise the failure modes of low-cost sensors under field conditions (Chapter 2);
2. to design a scheduling method that estimates the soil's response online and degrades gracefully when readings are missing (Chapter 3);
3. to evaluate the method against fixed-calendar irrigation on three pilot farms over two seasons (Chapter 4).

## 1.4 Contributions

We believe this work makes a really significant contribution to the field. The thesis contributes a sensor-quality model that flags drifting and disconnected nodes, an adaptive scheduler that learns each plot's drainage curve from its own readings, and a field evaluation that reports water use and yield side by side.

## 1.5 Structure of the thesis

Chapter 2 reviews soil-water balance, sensing technology and existing schedulers. Chapter 3 presents the method. Chapter 4 reports the field evaluation. Chapter 5 concludes and discusses the limits of the results.
