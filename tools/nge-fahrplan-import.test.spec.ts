import {NodeService} from "../app/services/data/node.service";
import {TrainrunService} from "../app/services/data/trainrun.service";
import {TrainrunSectionService} from "../app/services/data/trainrunsection.service";
import {BaseDataService} from "../app/services/data/basedata.service";
import {DataService} from "../app/services/data/data.service";
import {ResourceService} from "../app/services/data/resource.service";
import {LogService} from "../app/logger/log.service";
import {LogPublishersService} from "../app/logger/log.publishers.service";
import {NoteService} from "../app/services/data/note.service";
import {LabelService} from "../app/services/data/label.service";
import {LabelGroupService} from "../app/services/data/labelgroup.service";
import {FilterService} from "../app/services/ui/filter.service";
import {NetzgrafikColoringService} from "../app/services/data/netzgrafikColoring.service";
import example from "./test-data/nge_fahrplan_a.json";
import fixture from "./test-data/nge_fahrplan_b.json";

describe("nge-fahrplan import", () => {
  let dataService: DataService;
  let nodeService: NodeService;
  let trainrunService: TrainrunService;
  let trainrunSectionService: TrainrunSectionService;

  beforeEach(() => {
    const resourceService = new ResourceService();
    const logService = new LogService(new LogPublishersService());
    const labelGroupService = new LabelGroupService();
    const labelService = new LabelService(labelGroupService);
    const filterService = new FilterService(labelService, labelGroupService);
    trainrunService = new TrainrunService(logService, labelService, filterService);
    trainrunSectionService = new TrainrunSectionService(trainrunService, filterService);
    nodeService = new NodeService(resourceService, trainrunService, trainrunSectionService, labelService, filterService);
    const noteService = new NoteService(labelService, filterService);
    dataService = new DataService(resourceService, nodeService, trainrunSectionService, trainrunService,
      new BaseDataService(), noteService, labelService, labelGroupService, filterService, new NetzgrafikColoringService());
  });

  for (const [name, file] of [["example", example], ["fixture", fixture]] as const) {
    it("loads " + name, () => {
      const dto = JSON.parse(JSON.stringify(file));
      expect(() => dataService.loadNetzgrafikDto(dto)).not.toThrow();
      expect(nodeService.getNodes().length).toBe(file.nodes.length);
      expect(trainrunService.getTrainruns().length).toBe(file.trainruns.length);
      expect(trainrunSectionService.getTrainrunSections().length).toBe(file.trainrunSections.length);
      // jede Transition zeigt auf echte Ports, jede Section hat Ports an beiden Enden
      nodeService.getNodes().forEach((n) => {
        n.getTransitions().forEach((t) => {
          expect(n.getPort(t.getPortId1())).toBeDefined();
          expect(n.getPort(t.getPortId2())).toBeDefined();
        });
      });
      trainrunSectionService.getTrainrunSections().forEach((ts) => {
        expect(ts.getSourceNode().getPort(ts.getSourcePortId())).toBeDefined();
        expect(ts.getTargetNode().getPort(ts.getTargetPortId())).toBeDefined();
        expect(ts.getTravelTime()).toBeGreaterThan(0);
      });
      // Zeiten bleiben nach dem Laden erhalten
      const out = dataService.getNetzgrafikDto();
      const before = file.trainrunSections.map((s: any) => [s.sourceDeparture.time, s.targetArrival.time, s.targetDeparture.time, s.sourceArrival.time].join("/")).sort();
      const after = out.trainrunSections.map((s) => [s.sourceDeparture.time, s.targetArrival.time, s.targetDeparture.time, s.sourceArrival.time].join("/")).sort();
      expect(after).toEqual(before);
      console.log("NGEFAHRPLAN " + name + " OK nodes=" + out.nodes.length + " sections=" + out.trainrunSections.length);
    });
  }
});
