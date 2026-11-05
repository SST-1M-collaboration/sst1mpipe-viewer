#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 29 12:15:04 2022

@author: zrdz
"""

import numpy as np
##import bokeh
# import pandas as pd
import os
from glob import glob
from bokeh.plotting import figure
#from bokeh.models import NumberFormatter, DataTable, TableColumn, Band,BoxAnnotation
from bokeh.models import Select, Div ,TextInput ,Panel,  Tabs, Button, ColumnDataSource, CheckboxGroup
from bokeh.models import LassoSelectTool,BoxSelectTool
#from bokeh.models import BooleanFilter, GroupFilter, CDSView, Range1d, Span, HoverTool
from bokeh.layouts import layout

from datetime import datetime

from pkg_resources import resource_filename
from cts_core.camera import Camera
from digicampipe.instrument import geometry
from digicampipe.io.event_stream import event_stream, add_slow_data
import astropy.units as u

from my_bokeh import CameraDisplay #BokehPlot

class nsb_mon():
    def __init__(self,data_dir='/net/',tel=1):
        
        self.tel = tel
        
        self.data_dir = os.path.join(data_dir,"cs{}/data/raw/".format(tel))
        #self.data_dir = os.path.join("/net/cs{}/data/raw/".format(tel))
        print("you are trying to read files from", self.data_dir)
        try:
            self.year_list = next(os.walk(self.data_dir))[1]
        except:
            self.year_list = ["No data"]

        
        
        ### CAM GEOM 
        digicam_config_file = resource_filename('digicampipe','tests/resources/camera_config.cfg')
        digicam = Camera(_config_file=digicam_config_file)
        self.geom = geometry.generate_geometry_from_camera(camera=digicam)
        self.geom.pix_area = np.ones(self.geom.n_pixels)*482.05 *u.mm**2 ## ??????
        self.geom.pixel_width = self.geom.pix_area**.5 *1.1#/(3**.5) ## ??????
        #self.geom.frame=??

        self.n_pixels = self.geom.n_pixels
        self.pixels   = np.arange(self.n_pixels)
        
        
        self.mon_data = {'baselines_mean' : np.zeros(self.n_pixels),
                    'baselines_std'  : np.zeros(self.n_pixels)}
        self.sedges = [0]
        self.medges = [0]
        self.baslines_datasource = ColumnDataSource(data=self.mon_data)
        self.sel_inds=[]
        
        
        
        self.month_list = []
        self.day_list   = []
        self.zfits_list = []
        
        ########################
        #### Error Div :: 
        ########################
        
        
        
        self.err_div = Div(
            text="",
            width=1000,
            height=20,
        )

        self.selected_div = Div(
            text="{} channels selected".format(len(self.sel_inds)),
            width=1000,
            height=20,
        )
        
        # self.warn_div = Div(
        #     text='<p style="color:orange"> Warning : checking this box during observation is NOT safe </p>',
        #     width=100,
        #     height=10,
        # )
        
        



        
        ###########################
        ## file selection wisgets
        ###########################
        self.checkbox_last_file = CheckboxGroup(labels=['Allow last file acces'], active=[1])
        
        DSW = 80
        self.select_year = Select(title="Year", 
                             value="", 
                             options=self.year_list,
                             width=DSW)
        
        self.select_month = Select(title="Month", 
                              value="", 
                              options=[],
                              width=DSW)

        self.select_day   = Select(title="Day", 
                              value="", 
                              options=[],
                              width=DSW)
        
        self.select_zfits   = Select(title="zfits files", 
                              value="", 
                              options=[],
                              width=DSW*3)
        
        
        self.update_button = Button(label="Show last file",
                                    button_type="success",
                                    width=DSW)
        
        

        
        
        #######################
        ### Making plots & hist
        #######################
        
        # create the scatter plot
        self.scaterfig = figure(   width=600, 
                                   height=500, 
                                   min_border=10, 
                                   min_border_left=50,
                                   # toolbar_location="above",
                                   x_axis_label = 'Baseline mean',
                                   y_axis_label = 'Baseline st.d.',
                                   title="baselines : Mean Vs St.d.")
        self.scater_plot = self.scaterfig.scatter(   x='baselines_mean',
                                                     y='baselines_std',
                                                     source=self.baslines_datasource,
                                                     size=3, 
                                                     color="#3A5785",
                                                     alpha=0.6)
        self.scaterfig.add_tools(LassoSelectTool())
        self.scaterfig.add_tools(BoxSelectTool())
        self.scaterfig.select(BoxSelectTool  ).select_every_mousemove = False
        self.scaterfig.select(LassoSelectTool).select_every_mousemove = False
        
        ### create histograms
        self.h_means,self.hh_means,self.hh_means_s  = self.make_hist("mean baselines","ADC")
        self.h_stds, self.hh_stds, self.hh_stds_s   = self.make_hist("baselines std", "ADC")
        
        
        ########################
        #### Camera display :: 
        ########################
        
        self.cam_mean_display = CameraDisplay(geometry=self.geom,
                                        title="Mean baselines",
                                        image = np.zeros(self.n_pixels))
        self.cam_mean_display.add_colorbar()
            
        
        self.cam_std_display = CameraDisplay(geometry=self.geom,
                                        title="baselines st.d.",
                                        image = np.zeros(self.n_pixels))
        self.cam_std_display.add_colorbar()
        
        ##############
        ### LAYOUT
        ##############
        
        self.layout = layout([[self.select_year,
                               self.select_month,
                               self.select_day,
                               self.select_zfits,
                               self.update_button,
                               ],
                               [self.checkbox_last_file],
                               self.err_div,
                               [self.selected_div],
                               [self.h_means, 
                                self.h_stds,
                                self.scaterfig],
                               [self.cam_mean_display.figure,
                                self.cam_std_display.figure]],
                               )#sizing_mode='fixed')
        
        self.tab = Panel(child=self.layout,     title= "Telescope {}".format(self.tel))
        
        
    # p = figure(tools=TOOLS, width=600, height=600, min_border=10, min_border_left=50,
    #        toolbar_location="above", x_axis_location=None, y_axis_location=None,
    #        title="Linked Histograms")
    # p.background_fill_color = "#fafafa"
    # p.select(BoxSelectTool).select_every_mousemove = False
    # p.select(LassoSelectTool).select_every_mousemove = False

    # r = p.scatter(x, y, size=3, color="#3A5785", alpha=0.6)
    
    
        #### Events
        ###########
        self.checkbox_last_file.on_change("active",self.last_file_warning)
        
        self.update_button.on_click(self.update_files)
        
        self.select_year.on_change ("value", self.load_months)
        self.select_month.on_change("value", self.load_days)
        self.select_day.on_change("value", self.load_zfitss)
        
        self.select_zfits.on_change("value",self.zfits_callback)
        
        # self.select_year.value = self.year_list[-1]
        
        self.scater_plot.data_source.selected.on_change('indices', self.update_selection)
        
        
    ###################
    ####### Callbacks
    ###################
    
    def update_selection(self,attr, old, new):
        inds = new
        # print(inds)
        h1, _ = np.histogram(self.mon_data['baselines_mean'][inds],
                            bins=self.medges)
        hist_data = {'top': h1, 'left': self.medges[:-1], 'right': self.medges[1:]}
        self.hh_means_s.data_source.data = hist_data

        h2, _ = np.histogram(self.mon_data['baselines_std'][inds],
                            bins=self.sedges)
        hist_data = {'top': h2, 'left': self.sedges[:-1], 'right': self.sedges[1:]}
        self.hh_stds_s.data_source.data = hist_data
            

        # neg_inds = np.ones_like(self.pixels, dtype=np.bool)
        # neg_inds[inds] = False
        self.cam_mean_display.datasource.selected.indices = inds
        self.cam_std_display.datasource.selected.indices = inds
        if len(inds) == 0 or len(inds) == len(self.pixels):
            self.hh_means_s.data_source.data['top'] = np.zeros_like(h1)
            self.hh_stds_s.data_source.data['top'] = np.zeros_like(h1)
            self.cam_mean_display.datasource.selected.indices = []
            self.cam_std_display.datasource.selected.indices  = []
        self.sel_inds = inds
        self.selected_div.text="{} channels selected".format(len(self.sel_inds))
    
    
    def last_file_warning(self,attr, old, new):
        if self.checkbox_last_file.active[0] == 0:
            self.checkbox_last_file.labels[0] = 'Allow last file acces -- WARNING : checking this box during observation is NOT safe'
        else:
            self.checkbox_last_file.labels[0] = 'Allow last file acces'
                                                 
    def zfits_callback(self,attr, old, new):
        self.load_mon_data()
        
    
    def load_months(self,attr, old, new):
        try:
            self.select_month.options = next(os.walk(os.path.join(self.data_dir,
                                                        self.select_year.value)))[1]
        except:
            self.select_month.options = ["no data"]
        self.select_month.value = self.select_month.options[-1]

        
    def load_days(self,attr, old, new):
        try:
            self.select_day.options = next(os.walk(os.path.join(self.data_dir,
                                                      self.select_year.value,
                                                      self.select_month.value)))[1]
        except:
            self.select_day.options = ["No data"]
            
        self.select_day.value = self.select_day.options[-1]

        
    def load_zfitss(self,attr, old, new):
        # try:
        #     self.select_zfits.options = next(os.walk(os.path.join(self.data_dir,
        #                                                 self.select_year.value,
        #                                                 self.select_month.value,
        #                                                 self.select_day.value,
        #                                                 'SST1M1')))[2]
        
        try:
            if self.checkbox_last_file.active[0] == 0:
                lim = None
            else:
                lim =-1
            files_list = sorted(glob(os.path.join(self.data_dir,
                                                  self.select_year.value,
                                                  self.select_month.value,
                                                  self.select_day.value,
                                                  '*/*.fz'))
                                )[:lim]
            
            self.select_zfits.options = [os.path.basename(ff) for ff in files_list]
            
        except:
            self.select_zfits.options = ["No data"]
            
        if len(self.select_zfits.options) == 0:
            self.select_zfits.options = ["No data"]
            
        self.select_zfits.value = self.select_zfits.options[-1]
        
        
    ## update button callback
    def update_files(self):
        self.load_zfitss("","","")

    #################
    #### Load data
    #################
    
    def load_mon_data(self):

        n_mon_evt = 0
        # self.err_div.text='<p style="color:orange"> \
        #        reading  file {} please, wait</p>'.format(self.select_zfits.value)
        
        try:
            TELIDstr = self.select_zfits.value.split('_')[0]
            mon_file = os.path.join(self.data_dir,
                                    self.select_year.value,
                                    self.select_month.value,
                                    self.select_day.value,
                                    # 'SST1M{}'.format(self.tel),
                                    TELIDstr,
                                    self.select_zfits.value)

            data_stream = event_stream(
                filelist=[mon_file],
                max_events=1000
                )
            baselines_mean = np.zeros(self.n_pixels)
            baselines_std  = np.zeros(self.n_pixels)
            
    
            print('loading', mon_file)
            for ii,event in enumerate(data_stream):
                # for tel in event.r0.tels_with_data:
                    tel = event.r0.tels_with_data[0]
                    r0data = event.r0.tel[tel]
                    if r0data._camera_event_type.value==8:
                        n_mon_evt      += 1
                        baselines_mean += r0data.adc_samples.mean(axis=1)
                        baselines_std  += r0data.adc_samples.std(axis=1)
                        
                        if n_mon_evt >100:
                            break
        except:
            self.err_div.text='<p style="color:red">Error : \
                wasn\'t able to read  file {} --'.format(mon_file)
            if os.path.exists(mon_file):
                self.err_div.text += " (file exist!) </p>"
            else:
                self.err_div.text += " (file not found) </p>"
            return
        
        if n_mon_evt == 0:
            ## err no baselines
            self.err_div.text='<p style="color:red">Error : \
                No baselines events found in file {} </p>'.format(mon_file)
            return
        
        
        self.err_div.text=""
        
        baselines_mean = baselines_mean / n_mon_evt
        baselines_std  = baselines_std  / n_mon_evt
        
        self.mon_data = {'baselines_mean' : baselines_mean,
                         'baselines_std'  : baselines_std}
                    
        self.baslines_datasource.data=self.mon_data
        
        h, self.medges = np.histogram( baselines_mean, bins=100 )
        hist_data = {'top': h, 'left': self.medges[:-1], 'right': self.medges[1:]}
        self.hh_means.data_source.data   = hist_data

        
        h,  self.sedges  = np.histogram( baselines_std,  bins=100 )
        hist_data = {'top': h, 'left': self.sedges[:-1], 'right': self.sedges[1:]}
        self.hh_stds.data_source.data = hist_data

        
        h, _ = np.histogram(self.mon_data['baselines_mean'][self.sel_inds],
                            bins=self.medges)
        hist_data = {'top': h, 'left': self.medges[:-1], 'right': self.medges[1:]}
        self.hh_means_s.data_source.data = hist_data

        h, _ = np.histogram(self.mon_data['baselines_std'][self.sel_inds],
                            bins=self.sedges)
        hist_data = {'top': h, 'left': self.sedges[:-1], 'right': self.sedges[1:]}
        self.hh_stds_s.data_source.data = hist_data
        # print(self.mean_hist_ds.data)
        
        
        self.cam_std_display.datasource.data['values'] = self.mon_data['baselines_std']
        self.cam_std_display.rescale()
        ## self.cam_std_displayset_limits_minmax(
                ## mon_data['baselines_std'][mon_data['baselines_std']>0].min(),
                ## mon_data['baselines_std'].max())
        self.cam_mean_display.datasource.data['values'] = self.mon_data['baselines_mean']
        self.cam_mean_display.rescale()
        
    def make_hist(self,title,x_axis_label):
        p = figure(plot_width = 600, 
            plot_height = 500,
            title = title,
            x_axis_label = x_axis_label, 
            y_axis_label = 'Count')

        # Add a quad
        h = p.quad(bottom=0, 
                   top=[0], 
                   left=[0], 
                   right=[0], 
                   fill_color="#3A5785",
                   hover_fill_alpha=0.7,
                   # hover_fill_color='blue',
                   line_color='black',
                   )
        ## histo of selected pixels
        h_sel = p.quad(bottom=0, 
                   top=[0], 
                   left=[0], 
                   right=[0], 
                   fill_color='red',
                   hover_fill_alpha=0.7,
                   # hover_fill_color='blue',
                   line_color='black',
                   )
        
        # p.add_tools(BoxSelectTool())
        
        # Add style to the plot
        p.title.align = 'center'
        p.title.text_font_size = '18pt'
        p.xaxis.axis_label_text_font_size  = '12pt'
        p.xaxis.major_label_text_font_size = '12pt'
        p.yaxis.axis_label_text_font_size  = '12pt'
        p.yaxis.major_label_text_font_size = '12pt'
        
        return p,h,h_sel
    
