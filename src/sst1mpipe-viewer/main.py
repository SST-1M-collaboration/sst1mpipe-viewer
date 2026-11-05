#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 29 12:15:04 2022

@author: zrdz
"""


from bokeh.io import curdoc
from bokeh.models import Div, Panel,  Tabs
from bokeh.layouts import layout
from nsb_mon import nsb_mon
import sys
#################################################################
##############    CREATE HTML CONTENT          ##################
#################################################################
div1 = Div(
    text="""
        <h1>SST-1M baseline Viewer </h1>
        
        """,
    width=1000,
    height=60,
)


div2 = Div(
    text="""
        <img align='right' src='sst_mon/static/logo.png' alt='logo'>
        """,
    width=50,
    height=60,
    align='end'
)

foot_div = Div(
    text="""
        <p> Bug report : tavernier@fzu.cz</p>
        """,

)

data_dir=sys.argv[1]

### TEL 1    
mon_cs1 = nsb_mon(data_dir=data_dir, tel=1)
try:
    mon_cs1.select_year.value = mon_cs1.year_list[-1]
    #mon_cs1.select_year.value = "2023"
except:
    mon_cs1.err_div.text= "ERROR : Did not found any data. (Data Disk not mounted ?)"
    
  
### TEL 2 
mon_cs2 = nsb_mon(data_dir=data_dir, tel=2)
try:
    mon_cs2.select_year.value = mon_cs2.year_list[-1]
    #mon_cs2.select_year.value = "2023"
except:
    mon_cs2.err_div.text= "ERROR : Did not found any data. (Data Disk not mounted ?)"



    

# mon_cs2.p = mon_cs2.make_hist(mon_cs2.mean_hist_ds,"mean baselines","mean baseline")
# mon_cs2. load_mon_data()


tab_cs1     = Panel(child=mon_cs1.layout,     title= "Telescope 1")
tab_cs2     = Panel(child= mon_cs2.layout,    title= "Telescope 2")

tabs = Tabs(tabs=[mon_cs1.tab, mon_cs2.tab])

full_layout = layout([[div1,div2],
                      [tabs],
                      [foot_div]])


curdoc().add_root(full_layout)
    
    

    
    
    
