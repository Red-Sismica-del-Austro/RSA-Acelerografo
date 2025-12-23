from dataclasses import dataclass
from obspy import UTCDateTime

@dataclass
class SeismicPick:
    network: str
    station: str
    phase: str  # 'P' or 'S'
    time: UTCDateTime
    probability: float
    channel: str

    def to_line(self):
        """Format as a line for the output file"""
        return f"{self.network} {self.station} {self.phase} {self.time.isoformat()} {self.probability:.4f} {self.channel}"

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "network": self.network,
            "station": self.station,
            "phase": self.phase,
            "time": self.time.isoformat(),
            "probability": self.probability,
            "channel": self.channel
        }
