#
# process Spektrum Flight Logs (TLM) after they have been
# parsed by flightlog.py --csv.
# author: paul sorenson


library(ggplot2)
library(reshape2)
library(data.table)
library(optparse)


option_list <- list(
    make_option('--filename', default='./logs/1408031156-450xTgye.csv',
        help='CSV file containing flightlogs (see flightlog.py)'),
    make_option('--charts', default='./charts',
        help='Location for chart images.'),
    make_option('--minv_start', default=11,
        help='Create charts where battery volts is at least this value.'),
    make_option('--tgap', default=15,
        help='Flights separated by less than tgap seconds are considered the same flight.'),
    make_option('--mintime', default=30,
        help='Create charts for logs greater than seconds')
    )


opt <- parse_args(OptionParser(option_list=option_list))

dir.create(opt$charts, recursive=TRUE)


colClasses <- c(flightno="numeric", value="character")

fl <- read.csv(opt$filename, colClasses=colClasses)

# fl$value <- as.numeric(as.character())

#summary(fl)

fld <- droplevels(fl[fl$rectype == "data",])
fld$value <- as.numeric(fld$value)

dt <- data.table(fld)
rm(fld)
setkey(dt, flightno, datatype, timestamp, parameter)


# Add elapsed flight time
dt[, 
   `:=`(elapsed=timestamp - min(timestamp)),
   by=flightno]


dt.w <- dcast.data.table(dt, modelname + offset + flightno + timestamp + elapsed ~ parameter, value.var="value")
setkey(dt.w, flightno, timestamp)

flights <- dt.w[, 
   list(elapsed=max(elapsed),
        tmin=min(timestamp, na.rm=TRUE), tmax=max(timestamp, na.rm=TRUE),
        rxmin=min(rxvolts, na.rm=TRUE), rxmax=max(rxvolts, na.rm=TRUE),
        vmin=min(Volt, na.rm=TRUE), vmax=max(Volt, na.rm=TRUE)),
   by=flightno]
setkey(flights, flightno)


# Calculate gap between flight logs - if timer settings are not just right then
# the timer can be interrupted which initiates another flight log.
flights$tgap <- c(NA, flights$tmin[-1] - flights$tmax[-nrow(flights)])
flights$vflag <- as.integer(flights$tgap > opt$tgap)
flights$vflag[1] <- flights$flightno[1]

# vflight (virtual flight) is a renumbered flight which joins
# flightlogs with gap < opt$tgap.
flights$vflightno <- cumsum(flights$vflag)  


## Reindex data based on vflightno
dt <- merge(dt, flights[, list(flightno, vflightno)], by.x="flightno", by.y='flightno')
setkey(dt, vflightno, datatype, timestamp, parameter)

# Add elapsed flight time
dt[, 
   `:=`(velapsed=timestamp - min(timestamp)),
   by=vflightno]


dt.w <- dcast.data.table(dt, modelname + offset + vflightno + timestamp + velapsed ~ parameter, 
                         value.var="value")
setkey(dt.w, vflightno, timestamp)

vflights <- dt.w[, 
                list(velapsed=max(velapsed),
                     tmin=min(timestamp, na.rm=TRUE), tmax=max(timestamp, na.rm=TRUE),
                     rxmin=min(rxvolts, na.rm=TRUE), rxmax=max(rxvolts, na.rm=TRUE),
                     vmin=min(Volt, na.rm=TRUE), vmax=max(Volt, na.rm=TRUE)),
                by=vflightno]
setkey(flights, vflightno)


parameters <- c("rxvolts", "Volt")


## Could plot from the wide version (dt.w) however there are NAs due to having
## different timeslots for different parameters.

today <- Sys.Date()

for (iflightno in vflights$vflightno) {
  f <- dt[vflightno == iflightno & parameter %in% parameters,]
  
  modelname <- levels(f$modelname)

  ggplot(f, aes(x=velapsed, y=value)) +
    #facet_grid(parameter ~ ., scales="free_y") +
    geom_line(aes(colour=parameter)) +
    #ylim(0, 12.5) +
    xlab("seconds") +
    ylab("volts") +
    ggtitle(sprintf("%s flight log index %04d", modelname, iflightno))

  ggsave(sprintf("%s/%s-450x-00-%04d.png", opt$charts, today, iflightno), dpi=90, 
         width=8, height=6, units="in")
}
