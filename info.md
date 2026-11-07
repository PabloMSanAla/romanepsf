# Measure the extended PSF for ROMAN SPACE TELESCOPE
### Dependencies 

Local rosalia:
/Users/pmsanch1/code/ROSALIA

### Simulated data of Roman
Simulated Level 2 dataset for a comissioning program. This is the data for testing. 

/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/*asdf


### References:
Similar methods used for different surveys:

https://academic.oup.com/mnras/article/491/4/5317/5625791
https://arxiv.org/pdf/2410.20190



### Task
Using the simulated Level 2 dataset, measure the extended PSF for the Roman Space Telescope.

### Steps

1. Load the simulated Level 2 dataset from the specified directory.
    1.1) Use roman_models library to upload the Level 2 dataset.
    1.2) Calibrate using the photometry info in the metadata.
2. Identify suitable stars for PSF measurement using gaia catalog.
    2.1) Find the stars center using the gaia and the refine the center using the image
    2.2) Avoid brigt stars that are located very close to each other
    2.1) Use flags from the level 2 such as saturated and do not use might help.

3. Extract postage stamps around the selected stars.
    3.1) You need to divide this steps into bright, medium and faint stars.
        Bright stars: Only use for the extended PSF wings.
        Faint stars: Primarily use for the core PSF.
        Medium stars: Use to unify core and extended PSF.
    
    3.2) Nomalize making a radial profile (profile.py) and identify a region that is not saturated, use flag info and the profile itself.

    3.3) stamps size should be different for bright, medium, and faint stars to properly capture the PSF features. 

    3.4) Resample and cetered properly the stars to ensure alignment before combining.
        For this fit a first moffat model using tools like astrophot to determine the initial center and shape parameters of the star. Then, one fitted, substract the model. The residual will be use to mask sources that are in the stamps that are not part of the star itself. DO NOT MASK THE SPIKES OF THE STARS. 
    
4. Model the extended PSF using the extracted stamps.

    4.1) Combine the normalized and resampled stamps to create a high signal-to-noise PSF model for each star category (bright, medium, faint).

    4.2) Combine the PSF models from different star categories to create a comprehensive extended PSF model that covers both the core and wings.

5. Validate the PSF model by substracting it from the observed star images and analyzing the residuals.

6. Document the results and any deviations observed.


### Parameters

The aim is to get a psf of a size of a detector (4089 pixels on a side). However, for testing purposes, get a smaller PSF of 512, 1024, 2048 pixels on a side. Start with the smallest then grow to larger to test the method. 

The parameters should all be given to the cli by the user via a yaml file. 

### Software

This all should be encapsule in a python package with a command-line interface (CLI) for ease of use and reproducibility. Should be easily install with a conda environment or pip install. 

### Preformance

Try to use gpu accelerate libraries like pytorch. However, this would be run in a machine 
for large dataset (over 30 footprins of WFI) with 32 CPUs and 64GB or 16CPU and 128GB of RAM.
Ensure that the code is optimized for memory usage and parallel processing to handle such large datasets efficiently.


## Documentation

The documentation should include:
- Description of the dataset and preprocessing steps.
- Criteria for selecting stars for PSF measurement.
- Details of the postage stamp extraction and normalization process.
- Methodology for modeling the extended PSF.
- Validation results and analysis of residuals.
- Performance optimization strategies used.
- Any deviations or challenges encountered during the process.


## Report

The report should include:
- Summary of the PSF modeling process.
- Key results and findings.
- Figures from the intermediate steps to illustrate the PSF modeling process, and ensure the correct functioning of each step.
- Comparison of the modeled PSF with observed star images.
- Analysis of residuals and any discrepancies.
- Performance evaluation and resource usage.
- Lessons learned and recommendations for future work.
